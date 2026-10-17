"""sw_common: the shared SentinelWard message contract (v1 + v1.1 additions).

Topics, message builders, validate/encode/decode, clock helpers and an MQTT Bus.
Everything except Bus is standard library only; Bus loads paho-mqtt on first use.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .clock import WINDOW_MS, now_ms, window_start_for
from .messages import (
    AGENT_IDS,
    ALARM_CODES,
    ALARM_PRIORITIES,
    ALERT_STATUSES,
    ALLOWED_ACTIONS,
    BED_IDS,
    BEDSIDE_RESULTS,
    CONTRACT_VERSION,
    DEMO_COMMANDS,
    FS,
    MESSAGE_TYPES,
    MODEL_IDS,
    MODEL_MEANING,
    PRIORITIES,
    RECORD_KINDS,
    REQUEST_ACTIONS,
    VERDICT_PRIORITY,
    MessageError,
    bed_for_device,
    decode,
    device_for_bed,
    encode,
    make_action,
    make_alert,
    make_bedside_check,
    make_demo_control,
    make_net_features,
    make_record,
    make_request,
    make_score,
    make_verdict,
    make_vitals,
    validate,
)
from .topics import (
    ACTION_TOPIC,
    ALERT_TOPIC,
    ALL_SUB,
    BEDSIDE_SUB,
    DEMO_CONTROL_TOPIC,
    NET_SUB,
    RECORD_TOPIC,
    REQUEST_TOPIC,
    SCORE_SUB,
    SUBSCRIPTIONS,
    VERDICT_SUB,
    VITALS_SUB,
    ParsedTopic,
    bedside_topic,
    check_pattern,
    net_topic,
    parse_topic,
    qos_retain_for,
    score_topic,
    topic_for,
    topic_matches,
    verdict_topic,
    vitals_topic,
)

if TYPE_CHECKING:
    from .bus import Bus

__version__ = "1.1.0"


def __getattr__(name: str) -> Any:
    # Lazy import keeps `import sw_common` working where paho-mqtt is not installed.
    if name == "Bus":
        from .bus import Bus

        return Bus
    raise AttributeError(f"module 'sw_common' has no attribute {name!r}")


__all__ = [
    # clock
    "now_ms", "window_start_for", "WINDOW_MS",
    # topics
    "vitals_topic", "score_topic", "verdict_topic", "bedside_topic", "net_topic",
    "ACTION_TOPIC", "ALERT_TOPIC", "REQUEST_TOPIC", "DEMO_CONTROL_TOPIC", "RECORD_TOPIC",
    "VITALS_SUB", "SCORE_SUB", "VERDICT_SUB", "BEDSIDE_SUB", "NET_SUB", "SUBSCRIPTIONS", "ALL_SUB",
    "ParsedTopic", "parse_topic", "topic_for", "qos_retain_for", "topic_matches", "check_pattern",
    # messages
    "make_vitals", "make_score", "make_verdict", "make_action", "make_alert", "make_bedside_check",
    "make_net_features", "make_request", "make_demo_control", "make_record",
    "validate", "encode", "decode", "MessageError",
    "CONTRACT_VERSION", "MESSAGE_TYPES", "FS", "VERDICT_PRIORITY", "PRIORITIES", "ALLOWED_ACTIONS",
    "ALARM_CODES", "ALARM_PRIORITIES", "MODEL_IDS", "MODEL_MEANING", "AGENT_IDS", "BED_IDS",
    "ALERT_STATUSES", "BEDSIDE_RESULTS", "REQUEST_ACTIONS", "DEMO_COMMANDS", "RECORD_KINDS",
    "device_for_bed", "bed_for_device",
    # bus
    "Bus",
    "__version__",
]
