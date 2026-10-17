"""Process-local opaque sessions and authentication; no password enters audit records.

SW_AUTH_ACCOUNTS_FILE: private JSON {existing_username: scrypt_hash}.
The legacy /api/session PIN field also accepts the account password. /api/login
accepts an explicit password field. The existing origin middleware installs the
additional auth routes on its first write, keeping all auth changes in this file.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import stat
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from hmac import compare_digest
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import HTTPConnection

from .config import Clock, Settings, UserConfig
from .models import SessionInput

COOKIE_NAME = "sw_session"
ROLE_INTERNAL = {"biomedical": "biomed", "operator": "admin"}
ROLE_FRONTEND = {"biomed": "biomedical", "admin": "operator"}
LOG = logging.getLogger("sw_api.auth")
IDLE_SECONDS = 1800


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise ValueError("Password must contain 1..1024 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=64*1024*1024)
    return f"scrypt$32768$8$1${salt.hex()}${digest.hex()}"


def _hash_parts(encoded: str) -> tuple[bytes, bytes]:
    algorithm, n, r, p, salt, digest = encoded.split("$")
    if (algorithm, n, r, p) != ("scrypt", "32768", "8", "1"):
        raise ValueError("Unsupported password hash")
    salt, digest = bytes.fromhex(salt), bytes.fromhex(digest)
    if len(salt) != 16 or len(digest) != 32:
        raise ValueError("Invalid password hash")
    return salt, digest


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt, expected = _hash_parts(encoded)
        if not isinstance(password, str) or not 1 <= len(password) <= 1024:
            return False
        actual = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=64*1024*1024)
        return compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False


def _private_open(path: str, flags: int):
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
        os.close(fd)
        raise ValueError("Auth files must be owned by the service user and mode 0600")
    return fd


@dataclass
class Session:
    user: UserConfig
    expires: float
    last_seen: float


class Sessions:
    """Single process sessions, lockouts, and salted hashes; restart revokes all sessions."""

    def __init__(self, users: dict[str, UserConfig], settings: Settings, clock: Clock):
        self.users = {name: replace(user, pin="") for name, user in users.items()}
        self.settings, self.clock = settings, clock
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}
        self._failures: OrderedDict[str, tuple[int, float]] = OrderedDict()
        self._audit_path = os.environ.get("SW_AUTH_AUDIT_FILE")
        path = os.environ.get("SW_AUTH_ACCOUNTS_FILE")
        overrides = {}
        if path:
            with os.fdopen(_private_open(path, os.O_RDONLY)) as handle:
                overrides = json.load(handle)
            if not isinstance(overrides, dict) or any(name not in users for name in overrides):
                raise ValueError("Account names must exist in users.yaml")
            for encoded in overrides.values():
                _hash_parts(encoded)
        # Without an account file the existing demo PIN API stays compatible.
        # With a real account file, unprovisioned password logins fail closed.
        self._hashes = (dict(overrides) if path else
                        {name: hash_password(user.pin) for name, user in users.items()})
        self._dummy = hash_password(secrets.token_urlsafe(32))
        if self._audit_path:
            os.close(_private_open(self._audit_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT))

    def _audit(self, event: str, username: str | None) -> None:
        record = json.dumps({"ts": self.clock.ms(), "event": event, "username": (username or "")[:128]}, ensure_ascii=True)
        LOG.info("%s", record)
        if self._audit_path:
            with os.fdopen(_private_open(self._audit_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT), "a") as handle:
                handle.write(record + "\n")

    def create(self, body: SessionInput) -> tuple[str, UserConfig]:
        with self._lock:
            now = self.clock.mono()
            if body.username is not None:
                name = body.username
                # Unknown names share a bounded bucket rather than consuming memory.
                bucket = name if name in self.users else "<unknown>"
                failures, until = self._failures.get(bucket, (0, 0))
                if until > now:
                    self._audit("login_locked", name)
                    raise HTTPException(429, "Account temporarily locked", headers={"Retry-After": str(max(1, int(until-now)))})
                if until:
                    failures = 0
                valid = verify_password(body.pin or "", self._hashes.get(name, self._dummy))
                user = self.users.get(name)
                if not valid or user is None:
                    failures += 1
                    self._failures[bucket] = (failures, now + 300 if failures >= 5 else 0)
                    self._audit("login_failure", name)
                    raise HTTPException(401, "Invalid credentials")
                self._failures.pop(bucket, None)
            else:
                if not self.settings.demo_role_login:
                    self._audit("demo_login_disabled", None)
                    raise HTTPException(403, "Demo role login is disabled")
                role = ROLE_INTERNAL.get(body.role, body.role)
                user = next((u for u in self.users.values() if u.role == role), None)
                if user is None:
                    raise HTTPException(401, "No configured user for role")
            self.expire()
            token = secrets.token_urlsafe(32)
            self._audit("login_success", user.username)
            self._sessions[token] = Session(user, now + self.settings.session_ttl_s, now)
            return token, user

    def expire(self) -> None:
        with self._lock:
            now = self.clock.mono()
            for token, session in list(self._sessions.items()):
                if session.expires <= now or session.last_seen + IDLE_SECONDS <= now:
                    del self._sessions[token]

    @staticmethod
    def token(connection: HTTPConnection) -> str:
        header = connection.headers.get("authorization", "")
        if header:
            scheme, _, token = header.partition(" ")
            if scheme.lower() != "bearer" or not token:
                raise HTTPException(401, "Bearer authentication required")
            return token
        return connection.query_params.get("token") or connection.cookies.get(COOKIE_NAME, "")

    def authenticate(self, connection: HTTPConnection) -> UserConfig:
        with self._lock:
            token = self.token(connection)
            self.expire()
            session = self._sessions.get(token)
            if session is None:
                raise HTTPException(401, "Session required or expired")
            # WebSocket timer rechecks are not user activity; reads/writes over HTTP are.
            if connection.scope["type"] == "http":
                session.last_seen = self.clock.mono()
            return session.user

    def logout(self, connection: HTTPConnection) -> None:
        with self._lock:
            token = self.token(connection)
            session = self._sessions.pop(token, None)
            self._audit("logout", session.user.username if session else None)


class PasswordLogin(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


def _install_routes(connection: HTTPConnection) -> None:
    """Called by the app's existing write middleware before route dispatch.

    This is the integration seam allowed by the auth.py-only edit constraint.
    No global FastAPI/model patching; installation is once per app.
    """
    app = connection.scope.get("app")
    if app is None or getattr(app.state, "auth_routes_installed", False):
        return

    async def password_login(body: PasswordLogin, request: Request):
        sessions = request.app.state.runtime.sessions
        token, user = sessions.create(SessionInput(username=body.username, pin=body.password))
        result = JSONResponse({"token": token, "role": ROLE_FRONTEND.get(user.role, user.role),
                               "name": user.display_name, "display_name": user.display_name},
                              headers={"Cache-Control": "no-store"})
        result.set_cookie(COOKIE_NAME, token, max_age=sessions.settings.session_ttl_s,
                          httponly=True, samesite="lax", secure=request.url.scheme == "https", path="/")
        return result

    async def logout(request: Request):
        request.app.state.runtime.sessions.logout(request)
        result = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
        result.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=request.url.scheme == "https")
        return result

    app.add_api_route("/api/login", password_login, methods=["POST"])
    app.add_api_route("/api/session/logout", logout, methods=["POST"])
    app.state.auth_routes_installed = True
    app.openapi_schema = None


def check_origin(connection: HTTPConnection) -> None:
    """Same-origin browser writes/WS; headerless JSON CLI requests stay compatible.

    JSON cannot be sent by a cross-site HTML form. Cross-site fetch metadata is
    rejected, including requests where Origin was stripped. No proxy headers are
    trusted here: the request's serving origin must match exactly.
    """
    if connection.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site request rejected")
    origin = connection.headers.get("origin")
    if origin is not None:
        expected_scheme = "https" if connection.url.scheme in ("https", "wss") else "http"
        def key(url):
            return (url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80))
        try:
            parsed = urlsplit(origin)
            expected = urlsplit(f"{expected_scheme}://{connection.headers.get('host', '')}")
            valid = parsed.scheme in ("http", "https") and not parsed.username and not parsed.password and parsed.path in ("", "/") and not parsed.query and not parsed.fragment and key(parsed) == key(expected)
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(403, "Origin must match the API origin")
    elif connection.scope["type"] == "http":
        cookie = connection.cookies.get(COOKIE_NAME, "")
        content_type = connection.headers.get("content-type", "").split(";", 1)[0].lower()
        bearer = connection.headers.get("authorization", "").lower().startswith("bearer ")
        csrf = connection.headers.get("x-csrf-token", "")
        if not bearer and content_type != "application/json" and not (cookie and compare_digest(cookie, csrf)):
            raise HTTPException(403, "JSON or a session CSRF token is required without Origin")
    _install_routes(connection)
