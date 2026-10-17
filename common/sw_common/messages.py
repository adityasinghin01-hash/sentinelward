"""SentinelWard message contract: constants, builders, validate(), encode() and decode().

Standard library only. The rules follow CONTRACT.md (v1 + v1.1 additions) exactly;
where the contract is silent, the value is accepted and a comment says so.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Callable, Mapping

from .clock import WINDOW_MS, now_ms

# --------------------------------------------------------------------------- constants

CONTRACT_VERSION = 1  # the value of "v"; the v1.1 additions (request, demo_control, record) keep "v": 1

MESSAGE_TYPES: tuple[str, ...] = (
    "vitals",
    "score",
    "verdict",
    "action",
    "alert",
    "bedside_check",
    "net_features",
    "request",
    "demo_control",
    "record",
)

FS = 125  # samples per second; ecg/ppg/abp hold exactly FS entries
REASON_MAX_CHARS = 120
MAX_REASONS = 3

PRIORITIES: tuple[str, ...] = ("high", "medium", "low", "none")

VERDICT_PRIORITY: dict[str, str] = {
    "NORMAL": "none",
    "EMERGENCY": "high",
    "BOTH": "high",
    "TAMPERING": "medium",
    "UNSURE": "medium",
    "DRIFTING": "medium",
    "LOOSE_SENSOR": "low",
    "DEVICE_ATTACK": "none",
}

ALARM_CODES: tuple[str, ...] = ("ASYSTOLE", "BRADY", "TACHY", "VTACH", "VFIB")
ALARM_PRIORITIES: tuple[str, ...] = ("high", "medium", "low")

MODEL_IDS: tuple[str, ...] = ("M1", "M2", "M3", "M4", "M5", "M6")
MODEL_MEANING: dict[str, str] = {
    "M1": "sensor unusable",
    "M2": "real emergency",
    "M3": "body mismatch",
    "M4": "replay",
    "M5": "network attack",
    "M6": "drift",
}

AGENT_IDS: tuple[str, ...] = tuple(f"A{i}" for i in range(1, 10))

# Key "staff" covers every person ("staff:<name>"). A9 exists as an agent ID but the
# contract's allow-list gives it no actions, so any action "by": "A9" is an error.
ALLOWED_ACTIONS: dict[str, frozenset[str]] = {
    "A1": frozenset({"send_message", "edit_message", "escalate", "record_ack"}),
    "A2": frozenset({"disable_client", "enable_client", "set_bed_untrusted"}),
    "A3": frozenset({"snapshot_files", "hash_file", "write_timeline"}),
    "A4": frozenset({"list_devices", "set_watch_level"}),
    "A5": frozenset({"draft_report", "start_clock"}),
    "A6": frozenset({"open_ticket", "update_ticket"}),
    "A7": frozenset({"warn_workload"}),
    "A8": frozenset({"write_briefing"}),
    "A9": frozenset(),
    "staff": frozenset({"bedside_check", "manual_reading", "undo", "mark_report_sent"}),
}

ALERT_STATUSES: tuple[str, ...] = ("open", "acked", "escalated", "closed")
BEDSIDE_RESULTS: tuple[str, ...] = ("patient_ok", "patient_not_ok")
REQUEST_ACTIONS: dict[str, str] = {  # request action -> what target_id refers to
    "ack_alert": "alert_id",
    "escalate_alert": "alert_id",
    "isolate_device": "device_id",
    "undo_action": "action_id",
    # doc 00 v1.2 (17 Oct): actions the screens' buttons need
    "fleet_hunt": "device_model",
    "contain_incident": "incident_id",
    "resolve_incident": "incident_id",
    "review_report": "report_id",
}
DEMO_COMMANDS: tuple[str, ...] = ("run", "reset")
RECORD_KINDS: tuple[str, ...] = ("ticket", "report", "incident", "briefing", "workload")

BED_IDS: tuple[str, ...] = tuple(f"B{i:02d}" for i in range(1, 13))

# Exactly two ASCII digits, 01-99 ("B00", "B3" and "B0003" are rejected). The ward has
# beds B01-B12 (BED_IDS); the checker validates the format, so B13-B99 also pass.
_BED_RE = re.compile(r"B(?:0[1-9]|[1-9][0-9])")
_DEVICE_RE = re.compile(r"MON-(?:0[1-9]|[1-9][0-9])")
# The contract only says "staff:<name>"; any non-empty name without whitespace is accepted.
_STAFF_RE = re.compile(r"staff:\S+")

_MODEL_SET = frozenset(MODEL_IDS)
_AGENT_SET = frozenset(AGENT_IDS)
_MAX_DEPTH = 64  # nesting limit for free-form JSON (extra, data, unknown fields)


def _is_bed_id(x: Any) -> bool:
    return type(x) is str and _BED_RE.fullmatch(x) is not None


def _is_device_id(x: Any) -> bool:
    return type(x) is str and _DEVICE_RE.fullmatch(x) is not None


def _is_model_id(x: Any) -> bool:
    return type(x) is str and x in _MODEL_SET


def _is_staff_id(x: Any) -> bool:
    return type(x) is str and _STAFF_RE.fullmatch(x) is not None


def device_for_bed(bed_id: str) -> str:
    """Return the monitor ID for a bed: "B03" -> "MON-03"."""
    if not _is_bed_id(bed_id):
        raise ValueError(f"device_for_bed: bed_id must look like 'B03' (B01..B99), got {bed_id!r}")
    return "MON-" + bed_id[1:]


def bed_for_device(device_id: str) -> str:
    """Return the bed ID for a monitor: "MON-03" -> "B03"."""
    if not _is_device_id(device_id):
        raise ValueError(f"bed_for_device: device_id must look like 'MON-03' (MON-01..MON-99), got {device_id!r}")
    return "B" + device_id[4:]


class MessageError(ValueError):
    """Raised by encode() (and Bus.publish) when a message breaks the contract."""

    def __init__(self, errors: list[str]) -> None:
        self.errors: list[str] = list(errors)
        shown = "; ".join(self.errors[:5])
        more = f" (+{len(self.errors) - 5} more)" if len(self.errors) > 5 else ""
        super().__init__(f"invalid message: {shown}{more}")


# --------------------------------------------------------------------------- check helpers

_MISSING = object()
Checker = Callable[[list, str, Any, bool], None]  # (errors, path, value, strict)


def _describe(x: Any) -> str:
    """JSON-flavoured name of a value's type, for error messages."""
    if x is None:
        return "null"
    t = type(x)
    if t is bool:
        return "boolean"
    if t is int:
        return "integer"
    if t is float:
        return "float" if math.isfinite(x) else "NaN/infinity"
    if t is str:
        return "string"
    if isinstance(x, (list, tuple)):
        return "list"
    if isinstance(x, dict):
        return "object"
    return t.__name__


def _short(x: Any) -> str:
    r = repr(x)
    return r if len(r) <= 40 else r[:37] + "..."


def _chk_int(errs: list, path: str, x: Any, *, nullable: bool = False, lo: int | None = None,
             hi: int | None = None) -> None:
    if x is None:
        if not nullable:
            errs.append(f"{path}: must not be null")
        return
    if type(x) is not int:
        errs.append(f"{path}: expected integer, got {_describe(x)}")
        return
    if lo is not None and hi is not None and not lo <= x <= hi:
        errs.append(f"{path}: expected an integer from {lo} to {hi}, got {x}")
    elif lo is not None and x < lo:
        errs.append(f"{path}: must be >= {lo}, got {x}")


def _chk_num(errs: list, path: str, x: Any, *, nullable: bool = False, unit: bool = False) -> None:
    if x is None:
        if not nullable:
            errs.append(f"{path}: must not be null")
        return
    t = type(x)
    if t is float:
        if not math.isfinite(x):
            errs.append(f"{path}: NaN and infinity are not allowed")
            return
    elif t is not int:
        errs.append(f"{path}: expected number, got {_describe(x)}")
        return
    if unit and not 0 <= x <= 1:
        errs.append(f"{path}: expected a number from 0 to 1, got {x!r}")


def _chk_str(errs: list, path: str, x: Any, *, nullable: bool = False, nonempty: bool = True,
             max_len: int | None = None) -> None:
    if x is None:
        if not nullable:
            errs.append(f"{path}: must not be null")
        return
    if type(x) is not str:
        errs.append(f"{path}: expected string, got {_describe(x)}")
        return
    if nonempty and not x:
        errs.append(f"{path}: must not be empty")
    if max_len is not None and len(x) > max_len:
        errs.append(f"{path}: at most {max_len} characters, got {len(x)}")


def _chk_enum(errs: list, path: str, x: Any, choices: tuple[str, ...] | Mapping[str, Any], *,
              nullable: bool = False) -> None:
    if x is None:
        if not nullable:
            errs.append(f"{path}: must not be null")
        return
    if type(x) is not str or x not in choices:
        errs.append(f"{path}: expected one of {', '.join(choices)}, got {_short(x)}")


def _chk_window_start(errs: list, path: str, x: Any) -> None:
    # The contract states the multiple-of-5000 rule for score; verdict and net_features
    # use the same 5-second windows (clock.window_start_for), so it is applied to all three.
    if type(x) is not int:
        _chk_int(errs, path, x)
    elif x % WINDOW_MS:
        errs.append(f"{path}: must be a multiple of {WINDOW_MS} ms, got {x}")


def _chk_signal(errs: list, path: str, x: Any) -> None:
    if x is None:
        return
    if not isinstance(x, (list, tuple)):
        errs.append(f"{path}: expected null or a list of {FS} numbers, got {_describe(x)}")
        return
    if len(x) != FS:
        errs.append(f"{path}: expected {FS} entries, got {len(x)}")
    bad = 0
    isfinite = math.isfinite
    for i, e in enumerate(x):
        te = type(e)
        if te is float:
            if isfinite(e):
                continue
            why = "NaN and infinity are not allowed"
        elif te is int or e is None:
            continue
        else:
            why = f"expected number or null, got {_describe(e)}"
        bad += 1
        if bad <= 3:
            errs.append(f"{path}[{i}]: {why}")
    if bad > 3:
        errs.append(f"{path}: {bad - 3} more invalid entries")


def _scan_json(errs: list, path: str, x: Any, depth: int = 0) -> None:
    """Check free-form content: JSON types only, no NaN/infinity anywhere."""
    if x is None or type(x) in (bool, int, str):
        return
    if type(x) is float:
        if not math.isfinite(x):
            errs.append(f"{path}: NaN and infinity are not allowed")
        return
    if depth >= _MAX_DEPTH:
        errs.append(f"{path}: nested deeper than {_MAX_DEPTH} levels")
        return
    if isinstance(x, dict):
        for k, v in x.items():
            if type(k) is not str:
                errs.append(f"{path}: object keys must be strings, got {_describe(k)} {_short(k)}")
                continue
            _scan_json(errs, f"{path}.{k}", v, depth + 1)
    elif isinstance(x, (list, tuple)):
        for i, v in enumerate(x):
            _scan_json(errs, f"{path}[{i}]", v, depth + 1)
    else:
        errs.append(f"{path}: a value of type {type(x).__name__} cannot be sent as JSON")


def _chk_extra_keys(errs: list, path: str, obj: dict, known: tuple[str, ...] | frozenset[str],
                    strict: bool, allow_extra: bool = False) -> None:
    for k, v in obj.items():
        if k in known:
            continue
        if type(k) is not str:
            errs.append(f"{path}: object keys must be strings, got {_describe(k)} {_short(k)}")
            continue
        if strict and not allow_extra:
            errs.append(f"{path}.{k}: unknown field (strict mode)")
        _scan_json(errs, f"{path}.{k}", v)


# --------------------------------------------------------------------------- field checkers
# Each checker has the signature (errs, path, value, strict).

def _int(nullable: bool = False, lo: int | None = None, hi: int | None = None) -> Checker:
    return lambda e, p, x, s: _chk_int(e, p, x, nullable=nullable, lo=lo, hi=hi)


def _num(nullable: bool = False, unit: bool = False) -> Checker:
    return lambda e, p, x, s: _chk_num(e, p, x, nullable=nullable, unit=unit)


def _str(nullable: bool = False, nonempty: bool = True, max_len: int | None = None) -> Checker:
    return lambda e, p, x, s: _chk_str(e, p, x, nullable=nullable, nonempty=nonempty, max_len=max_len)


def _enum(choices: tuple[str, ...] | Mapping[str, Any], nullable: bool = False) -> Checker:
    return lambda e, p, x, s: _chk_enum(e, p, x, choices, nullable=nullable)


def _id(test: Callable[[Any], bool], like: str, nullable: bool = False) -> Checker:
    def check(errs: list, path: str, x: Any, strict: bool) -> None:
        if x is None:
            if not nullable:
                errs.append(f"{path}: must not be null")
        elif not test(x):
            errs.append(f"{path}: expected {like}, got {_short(x)}")
    return check


_TS = _int()  # all timestamps: integer epoch ms (the contract sets no range)
_TS_NULLABLE = _int(nullable=True)
_BED = _id(_is_bed_id, "a bed ID like 'B03' (B01..B99)")
_BED_NULLABLE = _id(_is_bed_id, "null or a bed ID like 'B03' (B01..B99)", nullable=True)
_DEVICE = _id(_is_device_id, "a device ID like 'MON-03' (MON-01..MON-99)")
_DEVICE_NULLABLE = _id(_is_device_id, "null or a device ID like 'MON-03'", nullable=True)
_MODEL = _id(_is_model_id, "a model ID M1..M6")
_ACTOR = _id(lambda x: (type(x) is str and x in _AGENT_SET) or _is_staff_id(x),
             "an agent ID A1..A9 or 'staff:<name>'")
_STAFF = _id(_is_staff_id, "'staff:<name>'")
# The contract gives no format for action_id, alert_id, request_id, record_id, run_id or
# model_version, so any non-empty string is accepted.
_NAME = _str()
_NAME_NULLABLE = _str(nullable=True)


def _window_start(errs: list, path: str, x: Any, strict: bool) -> None:
    _chk_window_start(errs, path, x)


def _signal(errs: list, path: str, x: Any, strict: bool) -> None:
    _chk_signal(errs, path, x)


def _fs(errs: list, path: str, x: Any, strict: bool) -> None:
    if type(x) is not int or x != FS:
        errs.append(f"{path}: expected {FS}, got {_short(x)}")


def _nibp(errs: list, path: str, x: Any, strict: bool) -> None:
    if x is None:
        return
    if not isinstance(x, dict):
        errs.append(f"{path}: expected null or an object with sys, dia, map, ts, got {_describe(x)}")
        return
    for k in ("sys", "dia", "map"):
        if k not in x:
            errs.append(f"{path}.{k}: required field is missing")
        else:
            # The contract does not say whether one cuff value may be null; null is accepted.
            _chk_num(errs, f"{path}.{k}", x[k], nullable=True)
    if "ts" not in x:
        errs.append(f"{path}.ts: required field is missing")
    else:
        _chk_int(errs, f"{path}.ts", x["ts"])
    _chk_extra_keys(errs, path, x, ("sys", "dia", "map", "ts"), strict)


def _alarm(errs: list, path: str, x: Any, strict: bool) -> None:
    if x is None:
        return
    if not isinstance(x, dict):
        errs.append(f"{path}: expected null or an object with code and priority, got {_describe(x)}")
        return
    for k, choices in (("code", ALARM_CODES), ("priority", ALARM_PRIORITIES)):
        if k not in x:
            errs.append(f"{path}.{k}: required field is missing")
        else:
            _chk_enum(errs, f"{path}.{k}", x[k], choices)
    _chk_extra_keys(errs, path, x, ("code", "priority"), strict)


def _object(errs: list, path: str, x: Any, strict: bool) -> None:
    # score.extra and record.data: any JSON object (strict mode does not look inside).
    if not isinstance(x, dict):
        errs.append(f"{path}: expected an object, got {_describe(x)}")
        return
    _scan_json(errs, path, x)


def _reasons(errs: list, path: str, x: Any, strict: bool) -> None:
    if not isinstance(x, (list, tuple)):
        errs.append(f"{path}: expected a list of strings, got {_describe(x)}")
        return
    if len(x) > MAX_REASONS:
        errs.append(f"{path}: at most {MAX_REASONS} reasons, got {len(x)}")
    # The 120-character limit is stated for score.reason only; verdict reasons are not length-checked.
    for i, r in enumerate(x):
        if type(r) is not str:
            errs.append(f"{path}[{i}]: expected string, got {_describe(r)}")


def _scores(errs: list, path: str, x: Any, strict: bool) -> None:
    if not isinstance(x, dict):
        errs.append(f"{path}: expected an object of model -> score, got {_describe(x)}")
        return
    for k, v in x.items():
        if not _is_model_id(k):
            errs.append(f"{path}: unknown model key {_short(k)} (expected M1..M6)")
            continue
        _chk_num(errs, f"{path}.{k}", v, nullable=True, unit=True)  # null = model not eligible


def _recipients(errs: list, path: str, x: Any, strict: bool) -> None:
    # The contract shows ["staff:priya"] but does not restrict recipients; any non-empty strings pass.
    if not isinstance(x, (list, tuple)):
        errs.append(f"{path}: expected a list of strings, got {_describe(x)}")
        return
    for i, r in enumerate(x):
        _chk_str(errs, f"{path}[{i}]", r)


# --------------------------------------------------------------------------- per-type specs
# Every field the contract shows is required; a missing value is sent as null, not left out.

_NET_NUMERIC: tuple[str, ...] = (
    "msgs_per_s", "bytes_per_s", "iat_mean_ms", "iat_std_ms", "payload_mean", "payload_std",
    "senders", "connects_per_s", "malformed", "seq_gaps", "seq_repeats", "stale_ms",
)

_SPECS: dict[str, tuple[tuple[str, Checker], ...]] = {
    "vitals": (
        ("bed_id", _BED),
        ("device_id", _DEVICE),
        ("seq", _int(lo=0)),  # "+1 per message" spans messages; one message only shows an int >= 0
        ("ts", _TS),
        ("fs", _fs),
        ("ecg", _signal),
        ("ppg", _signal),
        ("abp", _signal),
        # Integer or float, finite, or null. The contract gives no ranges, so none are checked.
        ("hr", _num(nullable=True)),
        ("spo2", _num(nullable=True)),
        ("rr", _num(nullable=True)),
        ("nibp", _nibp),
        ("monitor_alarm", _alarm),
    ),
    "score": (
        ("bed_id", _BED),
        ("model", _MODEL),
        ("model_version", _NAME),
        ("window_start", _window_start),
        ("window_s", _int(lo=1)),  # example is 10; the contract does not fix the value
        ("score", _num(nullable=True, unit=True)),  # doc 00: missing = null (model not eligible)
        ("label", _NAME),  # the contract lists no labels, so any non-empty string passes
        ("reason", _str(nonempty=False, max_len=REASON_MAX_CHARS)),
        ("extra", _object),
    ),
    "verdict": (
        ("bed_id", _BED),
        ("ts", _TS),
        ("window_start", _window_start),
        ("verdict", _enum(VERDICT_PRIORITY)),
        ("priority", _enum(PRIORITIES)),
        ("confidence", _num(unit=True)),
        ("trust", _num(unit=True)),
        ("last_trusted_ts", _TS_NULLABLE),
        ("reasons", _reasons),
        ("scores", _scores),
    ),
    "action": (
        ("action_id", _NAME),
        ("ts", _TS),
        ("by", _ACTOR),
        ("action", _NAME),
        ("bed_id", _BED_NULLABLE),
        ("device_id", _DEVICE_NULLABLE),
        ("detail", _str(nonempty=False)),
        ("undo_id", _NAME_NULLABLE),
        ("undoes", _NAME_NULLABLE),
        ("approved_by", _NAME_NULLABLE),  # the contract gives no format; any non-empty string
        ("result", _NAME),  # example "ok"; the contract lists no values
    ),
    "alert": (
        ("alert_id", _NAME),
        ("ts", _TS),
        ("bed_id", _BED),
        ("verdict", _enum(VERDICT_PRIORITY)),
        # The verdict -> priority table is stated for verdict messages only; alerts accept any priority.
        ("priority", _enum(PRIORITIES)),
        ("text", _NAME),
        ("to", _recipients),
        ("ladder_step", _int(lo=1, hi=3)),
        ("status", _enum(ALERT_STATUSES)),
        ("acked_by", _NAME_NULLABLE),
        ("acked_ts", _TS_NULLABLE),
    ),
    "bedside_check": (
        ("bed_id", _BED),
        ("ts", _TS),
        ("result", _enum(BEDSIDE_RESULTS)),
        ("by", _STAFF),  # bedside_check is a people-only action in the allow-list
    ),
    "net_features": (
        ("device_id", _DEVICE),
        ("window_start", _window_start),
        ("window_s", _int(lo=1)),  # example is 5; the contract does not fix the value
        # Finite numbers; null is accepted by the general "missing value is null" rule.
        *((name, _num(nullable=True)) for name in _NET_NUMERIC),
    ),
    "request": (
        ("request_id", _NAME),
        ("ts", _TS),
        ("by", _ACTOR),  # example is staff; the contract does not forbid agents
        ("action", _enum(REQUEST_ACTIONS)),
        ("target_id", _NAME),
        ("bed_id", _BED_NULLABLE),
        ("note", _str(nonempty=False)),
    ),
    "demo_control": (
        ("ts", _TS),
        ("cmd", _enum(DEMO_COMMANDS)),
        ("run_id", _NAME),
        ("start_at_s", _int(lo=0)),
    ),
    "record": (
        ("ts", _TS),
        ("kind", _enum(RECORD_KINDS)),
        ("record_id", _NAME),
        ("by", _ACTOR),
        ("data", _object),
    ),
}

_KNOWN: dict[str, frozenset[str]] = {
    t: frozenset(("v", "type", *(name for name, _ in spec))) for t, spec in _SPECS.items()
}


def _cross_vitals(errs: list, m: dict) -> None:
    bed, dev = m.get("bed_id"), m.get("device_id")
    if _is_bed_id(bed) and _is_device_id(dev) and dev[4:] != bed[1:]:
        errs.append(f"vitals.device_id: {dev!r} does not belong to bed_id {bed!r} (expected 'MON-{bed[1:]}')")


def _cross_verdict(errs: list, m: dict) -> None:
    verdict, priority = m.get("verdict"), m.get("priority")
    if type(verdict) is str and verdict in VERDICT_PRIORITY and type(priority) is str and priority in PRIORITIES:
        want = VERDICT_PRIORITY[verdict]
        if priority != want:
            errs.append(f"verdict.priority: verdict {verdict} requires priority {want!r}, got {priority!r}")


def _cross_action(errs: list, m: dict) -> None:
    by, action = m.get("by"), m.get("action")
    key = "staff" if _is_staff_id(by) else by if (type(by) is str and by in _AGENT_SET) else None
    if key is not None and type(action) is str and action:
        allowed = ALLOWED_ACTIONS[key]
        if action not in allowed:
            listed = ", ".join(sorted(allowed)) or "nothing"
            errs.append(f"action.action: {action!r} is not allowed for {by} (allowed: {listed})")
    if action == "undo" and m.get("undoes") is None and "undoes" in m:
        errs.append("action.undoes: an 'undo' action must name the original action_id in undoes")
    bed, dev = m.get("bed_id"), m.get("device_id")
    if _is_bed_id(bed) and _is_device_id(dev) and dev[4:] != bed[1:]:
        errs.append(f"action.device_id: {dev!r} does not belong to bed_id {bed!r} (expected 'MON-{bed[1:]}')")


def _cross_request(errs: list, m: dict) -> None:
    # Only device IDs have a fixed format; alert_id and action_id targets are any non-empty string.
    target = m.get("target_id")
    if m.get("action") == "isolate_device" and type(target) is str and target and not _is_device_id(target):
        errs.append(f"request.target_id: isolate_device needs a device ID like 'MON-03', got {_short(target)}")


_CROSS: dict[str, Callable[[list, dict], None]] = {
    "vitals": _cross_vitals,
    "verdict": _cross_verdict,
    "action": _cross_action,
    "request": _cross_request,
}


# --------------------------------------------------------------------------- validate

def validate(message: Any, strict: bool = False) -> list[str]:
    """Check a message against the contract; return a list of errors (empty = valid).

    Unknown extra keys are allowed; with strict=True they are errors, except in net_features.
    """
    if not isinstance(message, dict):
        return [f"message: expected a JSON object, got {_describe(message)}"]
    errs: list[str] = []
    mtype = message.get("type", _MISSING)
    known_type = type(mtype) is str and mtype in _SPECS
    if mtype is _MISSING:
        errs.append("message.type: required field is missing")
    elif not known_type:
        errs.append(f"message.type: expected one of {', '.join(MESSAGE_TYPES)}, got {_short(mtype)}")
    prefix = mtype if known_type else "message"

    v = message.get("v", _MISSING)
    if v is _MISSING:
        errs.append(f"{prefix}.v: required field is missing")
    elif type(v) is not int or v != CONTRACT_VERSION:
        errs.append(f"{prefix}.v: expected {CONTRACT_VERSION}, got {_short(v)}")
    if not known_type:
        return errs

    for name, check in _SPECS[mtype]:
        if name in message:
            check(errs, f"{mtype}.{name}", message[name], strict)
        else:
            errs.append(f"{mtype}.{name}: required field is missing")
    cross = _CROSS.get(mtype)
    if cross is not None:
        cross(errs, message)

    known = _KNOWN[mtype]
    if not message.keys() <= known:
        _chk_extra_keys(errs, mtype, message, known, strict, allow_extra=(mtype == "net_features"))
    return errs


# --------------------------------------------------------------------------- encode / decode

def _sanitize(x: Any) -> Any:
    """Copy x with NaN/infinity replaced by None and tuples turned into lists."""
    if type(x) is float:
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _sanitize(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_sanitize(v) for v in x]
    return x


def encode(message: Mapping[str, Any], *, check: bool = True, strict: bool = False) -> bytes:
    """Return compact UTF-8 JSON bytes; NaN/infinity become null.

    Raises MessageError if the (cleaned) message is invalid, unless check=False.
    """
    try:
        clean = _sanitize(message)
    except RecursionError:
        raise MessageError(["message: nested too deeply to encode"]) from None
    if check:
        errors = validate(clean, strict)
        if errors:
            raise MessageError(errors)
    try:
        text = json.dumps(clean, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return text.encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise MessageError([f"message: cannot be encoded as JSON ({exc})"]) from exc


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not allowed in a message")


def decode(raw: bytes | bytearray | memoryview | str, *, strict: bool = False) -> tuple[dict | None, list[str]]:
    """Parse raw bytes into (message, errors); never raises.

    message is None when the bytes are not a JSON object; otherwise it is returned even if invalid.
    """
    try:
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, (bytes, bytearray, memoryview)):
            text = bytes(raw).decode("utf-8")
        else:
            return None, [f"message: expected bytes, got {type(raw).__name__}"]
    except UnicodeDecodeError as exc:
        return None, [f"message: not valid UTF-8 ({exc.reason} at byte {exc.start})"]
    except Exception as exc:  # e.g. a memoryview that cannot be copied
        return None, [f"message: unreadable payload ({type(exc).__name__}: {exc})"]
    try:
        obj = json.loads(text, parse_constant=_reject_constant)
    except RecursionError:
        return None, ["message: JSON nested too deeply"]
    except ValueError as exc:
        return None, [f"message: not valid JSON ({exc})"]
    except Exception as exc:
        return None, [f"message: not valid JSON ({type(exc).__name__}: {exc})"]
    if not isinstance(obj, dict):
        return None, [f"message: expected a JSON object, got {_describe(obj)}"]
    try:
        return obj, validate(obj, strict)
    except Exception as exc:  # validate is written not to raise; this is a last-resort guard
        return obj, [f"message: could not be checked ({type(exc).__name__}: {exc})"]


# --------------------------------------------------------------------------- builders

def _build(mtype: str, body: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    clash = {"v", "type"} & fields.keys()
    if clash:
        raise ValueError(f"make_{mtype}: {', '.join(sorted(clash))} is set by the builder")
    msg: dict[str, Any] = {"v": CONTRACT_VERSION, "type": mtype}
    msg.update(body)
    msg.update(fields)
    return msg


def make_vitals(*, bed_id: str, seq: int, ecg: list | None = None, ppg: list | None = None,
                abp: list | None = None, hr: float | None = None, spo2: float | None = None,
                rr: float | None = None, nibp: dict | None = None, monitor_alarm: dict | None = None,
                device_id: str | None = None, fs: int = FS, ts: int | None = None,
                **fields: Any) -> dict[str, Any]:
    """Build a vitals message; device_id defaults to the bed's monitor (B03 -> MON-03)."""
    return _build("vitals", {
        "bed_id": bed_id,
        "device_id": device_for_bed(bed_id) if device_id is None else device_id,
        "seq": seq,
        "ts": now_ms() if ts is None else ts,
        "fs": fs,
        "ecg": ecg,
        "ppg": ppg,
        "abp": abp,
        "hr": hr,
        "spo2": spo2,
        "rr": rr,
        "nibp": nibp,
        "monitor_alarm": monitor_alarm,
    }, fields)


def make_score(*, bed_id: str, model: str, model_version: str, window_start: int, score: float,
               label: str, reason: str, window_s: int = 10, extra: dict | None = None,
               **fields: Any) -> dict[str, Any]:
    """Build a score message (score has no "ts"; window_start is required)."""
    return _build("score", {
        "bed_id": bed_id,
        "model": model,
        "model_version": model_version,
        "window_start": window_start,
        "window_s": window_s,
        "score": score,
        "label": label,
        "reason": reason,
        "extra": {} if extra is None else extra,
    }, fields)


def make_verdict(*, bed_id: str, window_start: int, verdict: str, confidence: float, trust: float,
                 scores: dict[str, float], reasons: list[str] | tuple[str, ...] = (),
                 last_trusted_ts: int | None = None, priority: str | None = None,
                 ts: int | None = None, **fields: Any) -> dict[str, Any]:
    """Build a verdict message; priority defaults to VERDICT_PRIORITY[verdict]."""
    return _build("verdict", {
        "bed_id": bed_id,
        "ts": now_ms() if ts is None else ts,
        "window_start": window_start,
        "verdict": verdict,
        "priority": VERDICT_PRIORITY.get(verdict) if priority is None else priority,
        "confidence": confidence,
        "trust": trust,
        "last_trusted_ts": last_trusted_ts,
        "reasons": list(reasons),
        "scores": dict(scores),
    }, fields)


def make_action(*, action_id: str, by: str, action: str, detail: str = "", bed_id: str | None = None,
                device_id: str | None = None, undo_id: str | None = None, undoes: str | None = None,
                approved_by: str | None = None, result: str = "ok", ts: int | None = None,
                **fields: Any) -> dict[str, Any]:
    """Build an action message (an undo is an action whose undoes is the original action_id)."""
    return _build("action", {
        "action_id": action_id,
        "ts": now_ms() if ts is None else ts,
        "by": by,
        "action": action,
        "bed_id": bed_id,
        "device_id": device_id,
        "detail": detail,
        "undo_id": undo_id,
        "undoes": undoes,
        "approved_by": approved_by,
        "result": result,
    }, fields)


def make_alert(*, alert_id: str, bed_id: str, verdict: str, text: str, to: list[str] | tuple[str, ...],
               priority: str | None = None, ladder_step: int = 1, status: str = "open",
               acked_by: str | None = None, acked_ts: int | None = None, ts: int | None = None,
               **fields: Any) -> dict[str, Any]:
    """Build an alert message; priority defaults to VERDICT_PRIORITY[verdict]."""
    return _build("alert", {
        "alert_id": alert_id,
        "ts": now_ms() if ts is None else ts,
        "bed_id": bed_id,
        "verdict": verdict,
        "priority": VERDICT_PRIORITY.get(verdict) if priority is None else priority,
        "text": text,
        "to": list(to),
        "ladder_step": ladder_step,
        "status": status,
        "acked_by": acked_by,
        "acked_ts": acked_ts,
    }, fields)


def make_bedside_check(*, bed_id: str, result: str, by: str, ts: int | None = None,
                       **fields: Any) -> dict[str, Any]:
    """Build a bedside_check message (result: patient_ok or patient_not_ok)."""
    return _build("bedside_check", {
        "bed_id": bed_id,
        "ts": now_ms() if ts is None else ts,
        "result": result,
        "by": by,
    }, fields)


def make_net_features(*, device_id: str, window_start: int, msgs_per_s: float | None,
                      bytes_per_s: float | None, iat_mean_ms: float | None, iat_std_ms: float | None,
                      payload_mean: float | None, payload_std: float | None, senders: float | None,
                      connects_per_s: float | None, malformed: float | None, seq_gaps: float | None,
                      seq_repeats: float | None, stale_ms: float | None, window_s: int = 5,
                      **fields: Any) -> dict[str, Any]:
    """Build a net_features message; extra numeric features go in **fields."""
    return _build("net_features", {
        "device_id": device_id,
        "window_start": window_start,
        "window_s": window_s,
        "msgs_per_s": msgs_per_s,
        "bytes_per_s": bytes_per_s,
        "iat_mean_ms": iat_mean_ms,
        "iat_std_ms": iat_std_ms,
        "payload_mean": payload_mean,
        "payload_std": payload_std,
        "senders": senders,
        "connects_per_s": connects_per_s,
        "malformed": malformed,
        "seq_gaps": seq_gaps,
        "seq_repeats": seq_repeats,
        "stale_ms": stale_ms,
    }, fields)


def make_request(*, request_id: str, by: str, action: str, target_id: str, bed_id: str | None = None,
                 note: str = "", ts: int | None = None, **fields: Any) -> dict[str, Any]:
    """Build a request message (a screen button an agent must carry out)."""
    return _build("request", {
        "request_id": request_id,
        "ts": now_ms() if ts is None else ts,
        "by": by,
        "action": action,
        "target_id": target_id,
        "bed_id": bed_id,
        "note": note,
    }, fields)


def make_demo_control(*, cmd: str, run_id: str, start_at_s: int = 0, ts: int | None = None,
                      **fields: Any) -> dict[str, Any]:
    """Build a demo_control message (cmd: run or reset)."""
    return _build("demo_control", {
        "ts": now_ms() if ts is None else ts,
        "cmd": cmd,
        "run_id": run_id,
        "start_at_s": start_at_s,
    }, fields)


def make_record(*, kind: str, record_id: str, by: str, data: dict[str, Any], ts: int | None = None,
                **fields: Any) -> dict[str, Any]:
    """Build a record message; sending the same record_id again replaces the earlier one."""
    return _build("record", {
        "ts": now_ms() if ts is None else ts,
        "kind": kind,
        "record_id": record_id,
        "by": by,
        "data": data,
    }, fields)
