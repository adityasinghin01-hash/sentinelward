"""Settings from environment variables, ward.yaml / users.yaml loading, and the clock."""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from sw_common import now_ms

BACKEND_DIR = Path(__file__).resolve().parent.parent
RESOURCE_DIR = BACKEND_DIR if (BACKEND_DIR / "ward.yaml").is_file() else Path(sys.prefix) / "share" / "sentinelward"
SCHEMA_SQL = RESOURCE_DIR / "schema.sql"

ROLES: tuple[str, ...] = ("nurse", "doctor", "it", "biomed", "admin")
_BED_RE = re.compile(r"B(?:0[1-9]|[1-9][0-9])")
_DEVICE_RE = re.compile(r"MON-(?:0[1-9]|[1-9][0-9])")
_USERNAME_RE = re.compile(r"[a-z][a-z0-9_.-]{0,31}")
_PIN_RE = re.compile(r"[0-9]{4}")


class ConfigError(ValueError):
    """A settings value or YAML file is missing or malformed."""


# --------------------------------------------------------------------------- settings

@dataclass(frozen=True)
class Settings:
    """Runtime settings; see Settings.from_env for the environment variables."""

    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_user: str | None = None
    mqtt_pass: str | None = None
    pg_dsn: str = "memory"
    ward_yaml: Path = RESOURCE_DIR / "ward.yaml"
    users_yaml: Path = RESOURCE_DIR / "users.yaml"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    schema_sql: Path = SCHEMA_SQL
    demo_role_login: bool = True
    session_ttl_s: int = 28800
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    @property
    def use_memory_store(self) -> bool:
        """True when SW_PG_DSN is "memory" (development without PostgreSQL)."""
        return self.pg_dsn.strip().lower() == "memory"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Read MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, SW_PG_DSN, SW_WARD_YAML, SW_USERS_YAML,
        SW_API_PORT, SW_API_HOST, SW_DEMO_ROLE_LOGIN, SW_SESSION_TTL_S and SW_FRONTEND_DIST."""
        e = os.environ if env is None else env

        def text(name: str, default: str | None) -> str | None:
            value = e.get(name)
            return default if value is None or value.strip() == "" else value.strip()

        def port(name: str, default: int) -> int:
            raw = text(name, None)
            if raw is None:
                return default
            try:
                value = int(raw)
            except ValueError:
                raise ConfigError(f"{name} must be an integer port, got {raw!r}") from None
            if not 1 <= value <= 65535:
                raise ConfigError(f"{name} must be from 1 to 65535, got {value}")
            return value

        def positive_int(name: str, default: int) -> int:
            raw = text(name, str(default))
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ConfigError(f"{name} must be a positive integer") from None
            if value <= 0:
                raise ConfigError(f"{name} must be a positive integer")
            return value

        def boolean(name: str, default: bool) -> bool:
            raw = text(name, str(default)).lower()
            if raw in {"true", "1", "yes", "on"}:
                return True
            if raw in {"false", "0", "no", "off"}:
                return False
            raise ConfigError(f"{name} must be true or false")

        user = text("MQTT_USER", None)
        password = e.get("MQTT_PASS") or None
        if password is not None and user is None:
            raise ConfigError("MQTT_PASS is set but MQTT_USER is not")
        return cls(
            mqtt_host=text("MQTT_HOST", cls.mqtt_host) or cls.mqtt_host,
            mqtt_port=port("MQTT_PORT", cls.mqtt_port),
            mqtt_user=user,
            mqtt_pass=password,
            pg_dsn=text("SW_PG_DSN", cls.pg_dsn) or cls.pg_dsn,
            ward_yaml=Path(text("SW_WARD_YAML", str(cls.ward_yaml)) or cls.ward_yaml),
            users_yaml=Path(text("SW_USERS_YAML", str(cls.users_yaml)) or cls.users_yaml),
            api_host=text("SW_API_HOST", cls.api_host) or cls.api_host,
            api_port=port("SW_API_PORT", cls.api_port),
            demo_role_login=boolean("SW_DEMO_ROLE_LOGIN", cls.demo_role_login),
            session_ttl_s=positive_int("SW_SESSION_TTL_S", cls.session_ttl_s),
            frontend_dist=Path(text("SW_FRONTEND_DIST", str(cls.frontend_dist))),
        )


# --------------------------------------------------------------------------- ward.yaml

@dataclass(frozen=True)
class BedConfig:
    """One bed from ward.yaml (patient data is made up)."""

    bed_id: str
    device_id: str
    nurse: str | None
    initials: str
    age: int | None
    sex: str | None

    def patient(self) -> dict[str, Any]:
        """Return {initials, age, sex} for API responses."""
        return {"initials": self.initials, "age": self.age, "sex": self.sex}


@dataclass(frozen=True)
class WardConfig:
    """The ward: its beds in display order, plus the beds shown on the public preview."""

    name: str
    beds: tuple[BedConfig, ...]
    preview_beds: tuple[str, ...] = field(default_factory=tuple)

    def bed(self, bed_id: str) -> BedConfig | None:
        """Return the bed with this ID, or None."""
        for b in self.beds:
            if b.bed_id == bed_id:
                return b
        return None


def _load_yaml(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError:
        raise ConfigError(f"file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML ({exc})") from None


def load_ward(path: Path, users: Mapping[str, UserConfig] | None = None) -> WardConfig:
    """Load and check ward.yaml; raise ConfigError on any problem."""
    doc = _load_yaml(path)
    if users is None:
        users = load_users(path.with_name("users.yaml"))
    if not isinstance(doc, dict) or not isinstance(doc.get("beds"), list) or not doc["beds"]:
        raise ConfigError(f"{path}: expected a 'beds' list")
    ward = doc.get("ward") or {}
    if not isinstance(ward, dict):
        raise ConfigError(f"{path}: 'ward' must be a mapping")
    beds: list[BedConfig] = []
    seen_beds: set[str] = set()
    seen_devices: set[str] = set()
    for i, raw in enumerate(doc["beds"]):
        where = f"{path}: beds[{i}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: expected a mapping")
        bed_id, device_id = raw.get("bed_id"), raw.get("device_id")
        if not isinstance(bed_id, str) or not _BED_RE.fullmatch(bed_id):
            raise ConfigError(f"{where}: bed_id must look like B03, got {bed_id!r}")
        if not isinstance(device_id, str) or not _DEVICE_RE.fullmatch(device_id):
            raise ConfigError(f"{where}: device_id must look like MON-03, got {device_id!r}")
        if device_id[4:] != bed_id[1:]:
            raise ConfigError(f"{where}: bed {bed_id} must use monitor MON-{bed_id[1:]}, got {device_id}")
        if bed_id in seen_beds or device_id in seen_devices:
            raise ConfigError(f"{where}: duplicate bed {bed_id} or device {device_id}")
        seen_beds.add(bed_id)
        seen_devices.add(device_id)
        patient = raw.get("patient") or {}
        if (not isinstance(patient, dict) or not isinstance(patient.get("initials"), str)
                or not patient["initials"].strip()):
            raise ConfigError(f"{where}: patient.initials is required")
        age = patient.get("age")
        if age is not None and (type(age) is not int or not 0 <= age <= 130):
            raise ConfigError(f"{where}: patient.age must be an integer 0-130 or empty, got {age!r}")
        sex = patient.get("sex")
        if sex is not None and not isinstance(sex, str):
            raise ConfigError(f"{where}: patient.sex must be text, got {sex!r}")
        nurse = raw.get("nurse")
        if nurse is not None and (not isinstance(nurse, str) or not nurse.startswith("staff:")):
            raise ConfigError(f"{where}: nurse must be a staff ID like staff:priya, got {nurse!r}")
        if nurse is not None:
            user = users.get(nurse.removeprefix("staff:"))
            if user is None or user.role != "nurse":
                raise ConfigError(f"{where}: nurse must reference a configured nurse, got {nurse!r}")
        beds.append(BedConfig(bed_id, device_id, nurse, patient["initials"].strip(), age, sex))
    if seen_beds != {f"B{i:02}" for i in range(1, 13)}:
        raise ConfigError(f"{path}: beds must contain exactly B01 through B12")
    preview = ward.get("preview_beds")
    if preview is None:
        preview = [b.bed_id for b in beds[:4]]
    if (not isinstance(preview, list) or any(not isinstance(p, str) for p in preview)
            or sorted(preview) != ["B01", "B02", "B03", "B04"]):
        raise ConfigError(f"{path}: ward.preview_beds must contain exactly B01 through B04")
    return WardConfig(name=str(ward.get("name") or "Ward"), beds=tuple(beds), preview_beds=tuple(preview))


# --------------------------------------------------------------------------- users.yaml

@dataclass(frozen=True)
class UserConfig:
    """One demo user. staff_id is what goes into messages ("staff:<username>")."""

    username: str
    display_name: str
    role: str
    pin: str

    @property
    def staff_id(self) -> str:
        """Return "staff:<username>"."""
        return f"staff:{self.username}"


def load_users(path: Path) -> dict[str, UserConfig]:
    """Load and check users.yaml; return users by username."""
    doc = _load_yaml(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("users"), list) or not doc["users"]:
        raise ConfigError(f"{path}: expected a 'users' list")
    users: dict[str, UserConfig] = {}
    for i, raw in enumerate(doc["users"]):
        where = f"{path}: users[{i}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: expected a mapping")
        username, role, pin = raw.get("username"), raw.get("role"), raw.get("pin")
        if not isinstance(username, str) or not _USERNAME_RE.fullmatch(username):
            raise ConfigError(f"{where}: username must be lower-case letters/digits/_.- , got {username!r}")
        if role not in ROLES:
            raise ConfigError(f"{where}: role must be one of {', '.join(ROLES)}, got {role!r}")
        pin = str(pin) if type(pin) is int else pin
        if not isinstance(pin, str) or not _PIN_RE.fullmatch(pin):
            raise ConfigError(f"{where}: pin must be 4 digits (quote it in YAML), got {pin!r}")
        if username in users:
            raise ConfigError(f"{where}: duplicate username {username}")
        users[username] = UserConfig(username, str(raw.get("display_name") or username), role, pin)
    return users


# --------------------------------------------------------------------------- clock

class Clock:
    """Wall clock (epoch ms) and monotonic clock (seconds); tests replace it with a fake."""

    def ms(self) -> int:
        """Current Unix time in UTC milliseconds."""
        return now_ms()

    def mono(self) -> float:
        """Monotonic seconds, for ages and timeouts."""
        return time.monotonic()
