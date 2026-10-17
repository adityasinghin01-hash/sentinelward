"""Settings from environment variables (documented in deploy/agents2.env.example).

Secrets (MQTT password, Telegram token) are kept out of repr() and are never logged.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_NURSES = ("staff:priya", "staff:tom")
DEFAULT_DOCTOR = "staff:dr_mehta"
# Matches backend/ward.yaml: B01-B06 Priya, B07-B12 Tom.
DEFAULT_ROSTER = {f"B{i:02d}": ("staff:priya" if i <= 6 else "staff:tom") for i in range(1, 13)}
DEVICE_RE = re.compile(r"MON-\d\d", re.ASCII)
STAFF_RE = re.compile(r"staff:[A-Za-z0-9_.-]{1,40}", re.ASCII)


class ConfigError(ValueError):
    """A setting is malformed. The message never contains a secret value."""


def _first(env: Mapping[str, str], *names: str, default: str | None = None) -> str | None:
    for name in names:
        value = env.get(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return default


def _bool(env, name, default: bool) -> bool:
    value = _first(env, name)
    if value is None:
        return default
    if value.lower() in ("1", "true", "yes", "on"):
        return True
    if value.lower() in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false")


def _num(env, name, default: float, lo: float, hi: float) -> float:
    value = _first(env, name)
    if value is None:
        return default
    try:
        number = float(value)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None
    if not lo <= number <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}")
    return number


def _json(env, name, default):
    value = _first(env, name)
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise ConfigError(f"{name} must be JSON") from None


def _staff(value: str, name: str) -> str:
    if not isinstance(value, str) or not STAFF_RE.fullmatch(value):
        raise ConfigError(f"{name}: expected staff:<name>")
    return value


@dataclass(frozen=True)
class Settings:
    # hub
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = field(default=None, repr=False)
    mqtt_ca_file: str | None = None
    client_id: str = "sw-agents2"
    extra_subscriptions: tuple[str, ...] = ("ward/bed/+/score/M3", "ward/bed/+/score/M5")
    state_dir: Path = Path("state")
    tz: str = "Asia/Kolkata"
    ward_name: str = "Ward 4B (demo)"
    # people
    roster: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_ROSTER))
    nurses: tuple[str, ...] = DEFAULT_NURSES
    doctor: str = DEFAULT_DOCTOR
    charge_nurse: str = "staff:priya"
    # A1
    ladder_step_s: float = 30.0
    ladder_priorities: tuple[str, ...] = ("high", "medium")
    confirm_verdicts: int = 2
    clear_verdicts: int = 2
    unsure_confirm_verdicts: int = 6  # UNSURE is a doubt, not a finding: ~30 s before a nurse is paged
    unsure_clear_verdicts: int = 4    # an UNSURE alert closes only after 4 NORMAL verdicts in a row (~20 s)
    unsure_repage_s: float = 180.0    # no new UNSURE page to the same nurse within 3 min of the last one closing
    telegram_token: str | None = field(default=None, repr=False)
    telegram_chats: Mapping[str, int] = field(default_factory=dict)
    telegram_it_chat: int | None = None
    telegram_min_interval_s: float = 1.0
    # A2
    a2_min_confidence: float = 0.8
    # TAMPERING/DEVICE_ATTACK must hold this long (consecutive verdicts) before the hub cut-off;
    # BOTH cuts at once. Until then the bed is only marked untrusted, so a real alarm still gets through.
    a2_confirm_s: float = 20.0
    a2_force_dry_run: bool = False
    dynsec_options: str | None = None
    contain_audit: str | None = None
    monitor_credentials: str | None = None
    a2_reset_releases: bool = True
    # A3
    evidence_window_s: float = 600.0
    # A4
    device_models: Mapping[str, str] = field(default_factory=lambda: {f"MON-{i:02d}": "demo-monitor" for i in range(1, 13)})
    watch_minutes: float = 60.0
    a4_after_cutoff: bool = True
    # A5
    organisation: str | None = None
    reporter_name: str | None = None
    reporter_email: str | None = None
    reporter_phone: str | None = None
    # A6
    loose_repeats: int = 3
    loose_window_s: float = 600.0
    # A7
    workload_threshold: int = 40
    workload_window_s: float = 7200.0
    workload_every_s: float = 60.0
    # A8
    shift_start: str = "08:00"
    briefing_every_s: float = 600.0
    briefing_demo_at_s: float = 1140.0
    granite_url: str | None = None
    granite_timeout_s: float = 120.0
    granite_max_tokens: int = 120
    # Granite takes ~30-60 s on the LinuxONE CPU: start the T+19:00 demo briefing this many seconds early.
    granite_lead_s: float = 60.0

    @property
    def a2_dry_run(self) -> bool:
        return self.a2_force_dry_run or not self.dynsec_options

    def secrets(self) -> tuple[str, ...]:
        """Values that must never appear in a log line."""
        return tuple(s for s in (self.mqtt_password, self.telegram_token) if s)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        port_name = "SW_AGENTS_MQTT_PORT" if _first(env, "SW_AGENTS_MQTT_PORT") else "SENTINEL_MQTT_PORT"
        port = int(_num(env, port_name, 1883, 1, 65535))
        roster = _json(env, "SW_ROSTER", dict(DEFAULT_ROSTER))
        if not isinstance(roster, dict):
            raise ConfigError("SW_ROSTER must be a JSON object bed -> staff")
        for bed, staff in roster.items():
            if not re.fullmatch(r"B\d\d", str(bed)):
                raise ConfigError("SW_ROSTER: bad bed ID")
            _staff(staff, "SW_ROSTER")
        nurses = tuple(_staff(s.strip(), "SW_NURSES") for s in (_first(env, "SW_NURSES") or ",".join(DEFAULT_NURSES)).split(",") if s.strip())
        if not nurses:
            raise ConfigError("SW_NURSES must list at least one nurse")
        chats = _load_chats(env)
        it_chat = _first(env, "SW_TELEGRAM_IT_CHAT")
        models = _json(env, "SW_DEVICE_MODELS", None)
        if models is None:
            models = {f"MON-{i:02d}": "demo-monitor" for i in range(1, 13)}
        if not isinstance(models, dict) or not all(DEVICE_RE.fullmatch(str(k)) and isinstance(v, str) for k, v in models.items()):
            raise ConfigError("SW_DEVICE_MODELS must map MON-xx to a model name")
        extra = tuple(p.strip() for p in (_first(env, "SW_AGENTS_EXTRA_SUBS", default="ward/bed/+/score/M3,ward/bed/+/score/M5") or "").split(",") if p.strip())
        if _first(env, "SW_AGENTS_EXTRA_SUBS") == "none":
            extra = ()
        shift = _first(env, "SW_SHIFT_START", default="08:00")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", shift):
            raise ConfigError("SW_SHIFT_START must be HH:MM")
        granite = _first(env, "SW_GRANITE_URL")
        if granite and not re.fullmatch(r"https?://[A-Za-z0-9.\-\[\]:]+(/[A-Za-z0-9._\-/]*)?", granite):
            raise ConfigError("SW_GRANITE_URL must be an http(s) URL")
        prios = tuple(p.strip() for p in (_first(env, "SW_A1_LADDER_PRIORITIES", default="high,medium")).split(",") if p.strip())
        if not set(prios) <= {"high", "medium", "low"}:
            raise ConfigError("SW_A1_LADDER_PRIORITIES: use high, medium, low")
        return cls(
            mqtt_host=_first(env, "SW_AGENTS_MQTT_HOST", "SENTINEL_MQTT_HOST", default="127.0.0.1"),
            mqtt_port=port,
            mqtt_username=_first(env, "SW_AGENTS_MQTT_USERNAME", "SENTINEL_MQTT_USERNAME", "SW_MQTT_USER"),
            mqtt_password=_first(env, "SW_AGENTS_MQTT_PASSWORD", "SENTINEL_MQTT_PASSWORD", "SW_MQTT_PASS"),
            mqtt_ca_file=_first(env, "SW_AGENTS_MQTT_CA", "SENTINEL_MQTT_CA"),
            client_id=_first(env, "SW_AGENTS_CLIENT_ID", default="sw-agents2"),
            extra_subscriptions=extra,
            state_dir=Path(_first(env, "SW_AGENTS_STATE_DIR", default="state")),
            tz=_first(env, "SW_TZ", default="Asia/Kolkata"),
            ward_name=_first(env, "SW_WARD_NAME", default="Ward 4B (demo)"),
            roster=roster,
            nurses=nurses,
            doctor=_staff(_first(env, "SW_DOCTOR", default=DEFAULT_DOCTOR), "SW_DOCTOR"),
            charge_nurse=_staff(_first(env, "SW_CHARGE_NURSE", default=nurses[0]), "SW_CHARGE_NURSE"),
            ladder_step_s=_num(env, "SW_A1_LADDER_STEP_S", 30.0, 1, 600),
            ladder_priorities=prios,
            confirm_verdicts=int(_num(env, "SW_A1_CONFIRM_VERDICTS", 2, 1, 10)),
            clear_verdicts=int(_num(env, "SW_A1_CLEAR_VERDICTS", 2, 1, 10)),
            unsure_confirm_verdicts=int(_num(env, "SW_A1_UNSURE_CONFIRM_VERDICTS", 6, 1, 24)),
            unsure_clear_verdicts=int(_num(env, "SW_A1_UNSURE_CLEAR_VERDICTS", 4, 1, 24)),
            unsure_repage_s=_num(env, "SW_A1_UNSURE_REPAGE_S", 180, 0, 3600),
            telegram_token=_first(env, "SW_TELEGRAM_BOT_TOKEN"),
            telegram_chats=chats,
            telegram_it_chat=_chat_id(it_chat, "SW_TELEGRAM_IT_CHAT") if it_chat else None,
            telegram_min_interval_s=_num(env, "SW_TELEGRAM_MIN_INTERVAL_S", 1.0, 1.0, 10),
            a2_min_confidence=_num(env, "SW_A2_MIN_CONFIDENCE", 0.8, 0, 1),
            a2_confirm_s=_num(env, "SW_A2_CONFIRM_S", 20, 0, 600),
            a2_force_dry_run=_bool(env, "SW_A2_DRY_RUN", False),
            dynsec_options=_first(env, "SW_DYNSEC_OPTIONS"),
            contain_audit=_first(env, "SW_CONTAIN_AUDIT"),
            monitor_credentials=_first(env, "SW_MONITOR_CREDENTIALS"),
            a2_reset_releases=_bool(env, "SW_A2_RESET_RELEASES", True),
            evidence_window_s=_num(env, "SW_A3_WINDOW_S", 600, 10, 3600),
            device_models=models,
            watch_minutes=_num(env, "SW_A4_WATCH_MINUTES", 60, 1, 1440),
            a4_after_cutoff=_bool(env, "SW_A4_AFTER_CUTOFF", True),
            organisation=_first(env, "SW_ORG_NAME"),
            reporter_name=_first(env, "SW_REPORTER_NAME"),
            reporter_email=_first(env, "SW_REPORTER_EMAIL"),
            reporter_phone=_first(env, "SW_REPORTER_PHONE"),
            loose_repeats=int(_num(env, "SW_A6_LOOSE_REPEATS", 3, 1, 100)),
            loose_window_s=_num(env, "SW_A6_LOOSE_WINDOW_S", 600, 10, 86400),
            workload_threshold=int(_num(env, "SW_A7_THRESHOLD", 40, 1, 10000)),
            workload_window_s=_num(env, "SW_A7_WINDOW_S", 7200, 60, 86400),
            workload_every_s=_num(env, "SW_A7_EVERY_S", 60, 5, 3600),
            shift_start=shift,
            briefing_every_s=_num(env, "SW_A8_EVERY_S", 600, 0, 86400),
            briefing_demo_at_s=_num(env, "SW_A8_DEMO_AT_S", 1140, 0, 86400),
            granite_url=granite,
            granite_timeout_s=_num(env, "SW_GRANITE_TIMEOUT_S", 120, 1, 600),
            granite_max_tokens=int(_num(env, "SW_GRANITE_MAX_TOKENS", 120, 20, 400)),
            granite_lead_s=_num(env, "SW_A8_GRANITE_LEAD_S", 60, 0, 3600),
        )


def _chat_id(value, name) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name}: chat IDs must be integers") from None


def _load_chats(env) -> dict[str, int]:
    """staff -> Telegram chat ID, from SW_TELEGRAM_CHATS (JSON) and/or SW_TELEGRAM_RECIPIENTS_FILE."""
    chats: dict = {}
    path = _first(env, "SW_TELEGRAM_RECIPIENTS_FILE")
    if path:
        try:
            chats.update(json.loads(Path(path).read_text()))
        except (OSError, json.JSONDecodeError):
            raise ConfigError("SW_TELEGRAM_RECIPIENTS_FILE is unreadable or not JSON") from None
    inline = _json(env, "SW_TELEGRAM_CHATS", {})
    if not isinstance(inline, dict) or not isinstance(chats, dict):
        raise ConfigError("Telegram chats must be a JSON object staff -> chat ID")
    chats.update(inline)
    return {_staff(k, "Telegram chats"): _chat_id(v, "Telegram chats") for k, v in chats.items()}
