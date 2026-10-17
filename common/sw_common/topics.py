"""MQTT topic names, subscription wildcards, topic parsing and QoS/retain rules."""

from __future__ import annotations

from typing import Any, Mapping, NamedTuple

from .messages import MESSAGE_TYPES, _is_bed_id, _is_device_id, _is_model_id

ACTION_TOPIC = "ward/action"
ALERT_TOPIC = "ward/alert"
REQUEST_TOPIC = "ward/request"
DEMO_CONTROL_TOPIC = "ward/demo/control"
RECORD_TOPIC = "ward/record"

VITALS_SUB = "ward/bed/+/vitals"
SCORE_SUB = "ward/bed/+/score/+"
VERDICT_SUB = "ward/bed/+/verdict"
BEDSIDE_SUB = "ward/bed/+/bedside"
NET_SUB = "net/device/+/features"

# Message type -> the pattern that receives every message of that type.
SUBSCRIPTIONS: dict[str, str] = {
    "vitals": VITALS_SUB,
    "score": SCORE_SUB,
    "verdict": VERDICT_SUB,
    "action": ACTION_TOPIC,
    "alert": ALERT_TOPIC,
    "bedside_check": BEDSIDE_SUB,
    "net_features": NET_SUB,
    "request": REQUEST_TOPIC,
    "demo_control": DEMO_CONTROL_TOPIC,
    "record": RECORD_TOPIC,
}
ALL_SUB: tuple[str, ...] = tuple(SUBSCRIPTIONS.values())  # every contract topic, and nothing else

_FIXED: dict[str, str] = {
    ACTION_TOPIC: "action",
    ALERT_TOPIC: "alert",
    REQUEST_TOPIC: "request",
    DEMO_CONTROL_TOPIC: "demo_control",
    RECORD_TOPIC: "record",
}
_BED_KINDS: dict[str, str] = {"vitals": "vitals", "verdict": "verdict", "bedside": "bedside_check"}

# Vitals are QoS 0; everything else QoS 1. Only verdicts are retained.
_QOS_RETAIN: dict[str, tuple[int, bool]] = {t: (1, False) for t in MESSAGE_TYPES}
_QOS_RETAIN["vitals"] = (0, False)
_QOS_RETAIN["verdict"] = (1, True)


class ParsedTopic(NamedTuple):
    """The message type a topic carries, plus the IDs in the topic (None when absent)."""

    kind: str
    bed_id: str | None = None
    model: str | None = None
    device_id: str | None = None


def _need_bed(func: str, bed_id: Any) -> None:
    if not _is_bed_id(bed_id):
        raise ValueError(f"{func}: bed_id must look like 'B03' (B01..B99), got {bed_id!r}")


def vitals_topic(bed_id: str) -> str:
    """Return "ward/bed/<bed_id>/vitals"."""
    _need_bed("vitals_topic", bed_id)
    return f"ward/bed/{bed_id}/vitals"


def score_topic(bed_id: str, model: str) -> str:
    """Return "ward/bed/<bed_id>/score/<model>"."""
    _need_bed("score_topic", bed_id)
    if not _is_model_id(model):
        raise ValueError(f"score_topic: model must be one of M1..M6, got {model!r}")
    return f"ward/bed/{bed_id}/score/{model}"


def verdict_topic(bed_id: str) -> str:
    """Return "ward/bed/<bed_id>/verdict"."""
    _need_bed("verdict_topic", bed_id)
    return f"ward/bed/{bed_id}/verdict"


def bedside_topic(bed_id: str) -> str:
    """Return "ward/bed/<bed_id>/bedside"."""
    _need_bed("bedside_topic", bed_id)
    return f"ward/bed/{bed_id}/bedside"


def net_topic(device_id: str) -> str:
    """Return "net/device/<device_id>/features"."""
    if not _is_device_id(device_id):
        raise ValueError(f"net_topic: device_id must look like 'MON-03' (MON-01..MON-99), got {device_id!r}")
    return f"net/device/{device_id}/features"


def parse_topic(topic: str) -> ParsedTopic:
    """Split a contract topic into its kind (message type) and IDs; raise ValueError otherwise."""
    if type(topic) is not str:
        raise ValueError(f"parse_topic: topic must be a string, got {type(topic).__name__}")
    kind = _FIXED.get(topic)
    if kind is not None:
        return ParsedTopic(kind)
    parts = topic.split("/")
    if len(parts) in (4, 5) and parts[0] == "ward" and parts[1] == "bed":
        bed = parts[2]
        if not _is_bed_id(bed):
            raise ValueError(f"parse_topic: bad bed_id {bed!r} in topic {topic!r}")
        if len(parts) == 4 and parts[3] in _BED_KINDS:
            return ParsedTopic(_BED_KINDS[parts[3]], bed_id=bed)
        if len(parts) == 5 and parts[3] == "score":
            if not _is_model_id(parts[4]):
                raise ValueError(f"parse_topic: bad model {parts[4]!r} in topic {topic!r}")
            return ParsedTopic("score", bed_id=bed, model=parts[4])
    elif len(parts) == 4 and parts[0] == "net" and parts[1] == "device" and parts[3] == "features":
        if not _is_device_id(parts[2]):
            raise ValueError(f"parse_topic: bad device_id {parts[2]!r} in topic {topic!r}")
        return ParsedTopic("net_features", device_id=parts[2])
    raise ValueError(f"parse_topic: {topic!r} is not a SentinelWard topic")


def topic_for(message: Mapping[str, Any]) -> str:
    """Return the topic a message is published on, from its type and IDs."""
    if not isinstance(message, Mapping):
        raise ValueError(f"topic_for: expected a message dict, got {type(message).__name__}")
    mtype = message.get("type")
    if mtype == "vitals":
        return vitals_topic(message.get("bed_id"))  # type: ignore[arg-type]
    if mtype == "score":
        return score_topic(message.get("bed_id"), message.get("model"))  # type: ignore[arg-type]
    if mtype == "verdict":
        return verdict_topic(message.get("bed_id"))  # type: ignore[arg-type]
    if mtype == "bedside_check":
        return bedside_topic(message.get("bed_id"))  # type: ignore[arg-type]
    if mtype == "net_features":
        return net_topic(message.get("device_id"))  # type: ignore[arg-type]
    for topic, kind in _FIXED.items():
        if mtype == kind:
            return topic
    raise ValueError(f"topic_for: unknown message type {mtype!r}")


def qos_retain_for(message_type: str) -> tuple[int, bool]:
    """Return (qos, retain) for a message type: vitals (0, False), verdict (1, True), others (1, False)."""
    try:
        return _QOS_RETAIN[message_type]
    except (KeyError, TypeError):
        raise ValueError(f"qos_retain_for: unknown message type {message_type!r}") from None


def check_pattern(pattern: str) -> None:
    """Raise ValueError unless pattern is a valid MQTT subscription filter."""
    if type(pattern) is not str or not pattern:
        raise ValueError(f"subscription pattern must be a non-empty string, got {pattern!r}")
    parts = pattern.split("/")
    for i, seg in enumerate(parts):
        if seg == "#" and i != len(parts) - 1:
            raise ValueError(f"subscription pattern {pattern!r}: '#' must be the last level")
        if seg not in ("#", "+") and ("#" in seg or "+" in seg):
            raise ValueError(f"subscription pattern {pattern!r}: '+' and '#' must fill a whole level")


def topic_matches(pattern: str, topic: str) -> bool:
    """Return True if topic matches the MQTT subscription pattern (+ and # wildcards)."""
    p = pattern.split("/")
    t = topic.split("/")
    if topic.startswith("$") and p[0] in ("+", "#"):
        return False  # MQTT: wildcards at the first level do not match $SYS-style topics
    for i, seg in enumerate(p):
        if seg == "#":
            return i == len(p) - 1
        if i >= len(t) or (seg != "+" and seg != t[i]):
            return False
    return len(p) == len(t)
