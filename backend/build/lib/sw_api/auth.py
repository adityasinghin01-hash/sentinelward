"""Expiring opaque sessions, shared by HTTP and WebSocket clients."""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from hmac import compare_digest
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.requests import HTTPConnection

from .config import Clock, Settings, UserConfig
from .models import SessionInput

COOKIE_NAME = "sw_session"
ROLE_INTERNAL = {"biomedical": "biomed", "operator": "admin"}
ROLE_FRONTEND = {"biomed": "biomedical", "admin": "operator"}


@dataclass(frozen=True)
class Session:
    user: UserConfig
    expires: float


class Sessions:
    """Sessions live only for this process; login supplies server-derived identities."""

    def __init__(self, users: dict[str, UserConfig], settings: Settings, clock: Clock):
        self.users, self.settings, self.clock = users, settings, clock
        self._sessions: dict[str, Session] = {}

    def create(self, body: SessionInput) -> tuple[str, UserConfig]:
        if body.username is not None:
            user = self.users.get(body.username)
            if user is None or not compare_digest(user.pin, body.pin or ""):
                raise HTTPException(401, "Invalid username or PIN")
        else:
            if not self.settings.demo_role_login:
                raise HTTPException(403, "Demo role login is disabled")
            role = ROLE_INTERNAL.get(body.role, body.role)
            user = next((u for u in self.users.values() if u.role == role), None)
            if user is None:
                raise HTTPException(401, "No configured user for role")
        self.expire()
        token = secrets.token_urlsafe(32)
        self._sessions[token] = Session(user, self.clock.mono() + self.settings.session_ttl_s)
        return token, user

    def expire(self) -> None:
        for token, session in list(self._sessions.items()):
            if session.expires <= self.clock.mono():
                del self._sessions[token]

    def authenticate(self, connection: HTTPConnection) -> UserConfig:
        header = connection.headers.get("authorization", "")
        if header:
            scheme, _, token = header.partition(" ")
            if scheme.lower() != "bearer":
                raise HTTPException(401, "Bearer authentication required")
        else:
            token = connection.query_params.get("token") or connection.cookies.get(COOKIE_NAME, "")
        session = self._sessions.get(token)
        if session is None or session.expires <= self.clock.mono():
            self._sessions.pop(token, None)
            raise HTTPException(401, "Session required or expired")
        return session.user


def check_origin(connection: HTTPConnection) -> None:
    """Cookie-authenticated writes/WS must come from the serving origin."""
    origin = connection.headers.get("origin")
    if origin is None:
        return  # CLI clients don't send Origin.
    expected_scheme = "https" if connection.url.scheme in ("https", "wss") else "http"
    parsed = urlsplit(origin)
    expected = urlsplit(f"{expected_scheme}://{connection.headers.get('host', '')}")
    def key(url):
        return (url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80))
    try:
        valid = parsed.scheme in ("http", "https") and not parsed.username and not parsed.password and parsed.path in ("", "/") and not parsed.query and not parsed.fragment and key(parsed) == key(expected)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(403, "Origin must match the API origin")
