"""Tests for sw_common.topics: builders, wildcards, parse_topic/topic_for round trip, QoS rules."""

from __future__ import annotations

import pytest

from conftest import EXAMPLES
from sw_common import (
    ACTION_TOPIC,
    ALERT_TOPIC,
    ALL_SUB,
    BEDSIDE_SUB,
    DEMO_CONTROL_TOPIC,
    MESSAGE_TYPES,
    MODEL_IDS,
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


def test_topic_builders():
    assert vitals_topic("B03") == "ward/bed/B03/vitals"
    assert score_topic("B03", "M3") == "ward/bed/B03/score/M3"
    assert verdict_topic("B07") == "ward/bed/B07/verdict"
    assert bedside_topic("B07") == "ward/bed/B07/bedside"
    assert net_topic("MON-07") == "net/device/MON-07/features"
    assert (ACTION_TOPIC, ALERT_TOPIC, REQUEST_TOPIC, DEMO_CONTROL_TOPIC, RECORD_TOPIC) == (
        "ward/action", "ward/alert", "ward/request", "ward/demo/control", "ward/record")


@pytest.mark.parametrize("call", [
    lambda: vitals_topic("B0003"),
    lambda: vitals_topic("B00"),
    lambda: vitals_topic("B03/#"),
    lambda: score_topic("B03", "M7"),
    lambda: verdict_topic(None),
    lambda: bedside_topic("+"),
    lambda: net_topic("MON-3"),
])
def test_topic_builders_reject_bad_ids(call):
    with pytest.raises(ValueError):
        call()


@pytest.mark.parametrize("mtype", MESSAGE_TYPES)
def test_topic_for_and_parse_topic_round_trip(mtype):
    message = EXAMPLES[mtype]
    topic = topic_for(message)
    parsed = parse_topic(topic)
    assert parsed.kind == mtype
    for field in ("bed_id", "model", "device_id"):
        value = getattr(parsed, field)
        if value is not None:
            assert value == message[field]
    assert topic_matches(SUBSCRIPTIONS[mtype], topic)


def test_parse_topic_every_bed_and_model():
    for i in range(1, 13):
        bed = f"B{i:02d}"
        dev = f"MON-{i:02d}"
        assert parse_topic(vitals_topic(bed)) == ParsedTopic("vitals", bed_id=bed)
        assert parse_topic(verdict_topic(bed)) == ParsedTopic("verdict", bed_id=bed)
        assert parse_topic(bedside_topic(bed)) == ParsedTopic("bedside_check", bed_id=bed)
        assert parse_topic(net_topic(dev)) == ParsedTopic("net_features", device_id=dev)
        for model in MODEL_IDS:
            assert parse_topic(score_topic(bed, model)) == ParsedTopic("score", bed_id=bed, model=model)


@pytest.mark.parametrize("topic", [
    "", "ward", "ward/bed/B03", "ward/bed/B03/vitals/extra", "ward/bed/B3/vitals", "ward/bed/B03/score",
    "ward/bed/B03/score/M9", "net/device/MON-7/features", "net/device/MON-07/stats", "ward/alerts",
    "/ward/action", "ward/action/", "ward/bed/+/vitals",
])
def test_parse_topic_rejects_unknown_topics(topic):
    with pytest.raises(ValueError, match="parse_topic"):
        parse_topic(topic)


def test_parse_topic_rejects_non_string():
    with pytest.raises(ValueError):
        parse_topic(None)  # type: ignore[arg-type]


def test_topic_for_rejects_unknown_or_bad_messages():
    with pytest.raises(ValueError, match="unknown message type"):
        topic_for({"v": 1, "type": "gossip"})
    with pytest.raises(ValueError, match="bed_id"):
        topic_for({**EXAMPLES["vitals"], "bed_id": "B0003"})
    with pytest.raises(ValueError):
        topic_for(["not", "a", "dict"])  # type: ignore[arg-type]


def test_qos_retain_for():
    assert qos_retain_for("verdict") == (1, True)
    assert qos_retain_for("vitals") == (0, False)
    for mtype in MESSAGE_TYPES:
        if mtype not in ("vitals", "verdict"):
            assert qos_retain_for(mtype) == (1, False), mtype
    with pytest.raises(ValueError, match="unknown message type"):
        qos_retain_for("gossip")
    with pytest.raises(ValueError):
        qos_retain_for(None)  # type: ignore[arg-type]


def test_wildcards():
    assert VITALS_SUB == "ward/bed/+/vitals"
    assert SCORE_SUB == "ward/bed/+/score/+"
    assert VERDICT_SUB == "ward/bed/+/verdict"
    assert BEDSIDE_SUB == "ward/bed/+/bedside"
    assert NET_SUB == "net/device/+/features"
    assert set(SUBSCRIPTIONS) == set(MESSAGE_TYPES)
    assert len(ALL_SUB) == len(MESSAGE_TYPES)
    for pattern in ALL_SUB:
        check_pattern(pattern)


def test_wildcards_match_only_their_kind():
    topics = {mtype: topic_for(EXAMPLES[mtype]) for mtype in MESSAGE_TYPES}
    for sub_kind, pattern in SUBSCRIPTIONS.items():
        for kind, topic in topics.items():
            assert topic_matches(pattern, topic) == (kind == sub_kind), (pattern, topic)


def test_topic_matches_rules():
    assert topic_matches("ward/#", "ward/bed/B03/vitals")
    assert topic_matches("ward/#", "ward")
    assert topic_matches("#", "ward/action")
    assert not topic_matches("#", "$SYS/broker/uptime")
    assert not topic_matches("+/action", "$SYS/action")
    assert topic_matches("ward/bed/+/score/+", "ward/bed/B03/score/M1")
    assert not topic_matches("ward/bed/+/score/+", "ward/bed/B03/score")
    assert not topic_matches("ward/bed/+", "ward/bed/B03/vitals")
    assert topic_matches("ward/action", "ward/action")
    assert not topic_matches("ward/action", "ward/alert")


@pytest.mark.parametrize("pattern", ["", "ward/#/x", "ward/b+", "ward/bed#", None])
def test_check_pattern_rejects_bad_filters(pattern):
    with pytest.raises(ValueError):
        check_pattern(pattern)  # type: ignore[arg-type]
