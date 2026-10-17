"""Tests for sw_common.messages: validate, builders, encode/decode and constants."""

from __future__ import annotations

import json
import math
import statistics
import time

import pytest

from conftest import ABP, ECG, EXAMPLES, PPG
from sw_common import (
    ALLOWED_ACTIONS,
    BED_IDS,
    MESSAGE_TYPES,
    MODEL_MEANING,
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
    now_ms,
    validate,
)

NAN = float("nan")
INF = float("inf")


def has_error(errors: list[str], *needles: str) -> bool:
    return any(all(n in e for n in needles) for e in errors)


# --------------------------------------------------------------------------- 1. contract examples

@pytest.mark.parametrize("mtype", MESSAGE_TYPES)
def test_every_contract_example_is_valid(example, mtype):
    assert validate(example(mtype)) == []
    assert validate(example(mtype), strict=True) == []


def test_examples_cover_every_type():
    assert set(EXAMPLES) == set(MESSAGE_TYPES)


# --------------------------------------------------------------------------- 2. vitals values

def test_hr_zero_is_valid(example):
    m = example("vitals")
    m["hr"] = 0
    assert validate(m) == []


@pytest.mark.parametrize("field", ["hr", "spo2", "rr"])
def test_vital_signs_accept_int_float_and_null(example, field):
    for value in (0, 0.0, 82, 82.5, None):
        m = example("vitals")
        m[field] = value
        assert validate(m) == [], value


@pytest.mark.parametrize("bad", [NAN, INF, -INF])
def test_hr_nan_and_infinity_fail(example, bad):
    m = example("vitals")
    m["hr"] = bad
    assert validate(m) == ["vitals.hr: NaN and infinity are not allowed"]


@pytest.mark.parametrize("bad", ["82", True, [82], {"hr": 82}])
def test_hr_wrong_type_fails(example, bad):
    m = example("vitals")
    m["hr"] = bad
    assert has_error(validate(m), "vitals.hr: expected number")


def test_ecg_with_124_entries_fails(example):
    m = example("vitals")
    m["ecg"] = ECG[:124]
    assert validate(m) == ["vitals.ecg: expected 125 entries, got 124"]


def test_ecg_null_is_valid(example):
    m = example("vitals")
    m["ecg"] = None
    assert validate(m) == []


def test_all_signals_null_is_valid(example):
    m = example("vitals")
    m["ecg"] = m["ppg"] = m["abp"] = None
    assert validate(m) == []


def test_abp_entries_null_are_valid(example):
    m = example("vitals")
    m["abp"] = [None] * 60 + ABP[60:]
    assert validate(m) == []


def test_flatline_zeros_are_valid(example):
    m = example("vitals")
    m["ecg"] = [0] * 125
    m["ppg"] = [0.0] * 125
    assert validate(m) == []


def test_signal_entry_nan_fails_with_index(example):
    m = example("vitals")
    m["ppg"] = list(PPG)
    m["ppg"][7] = NAN
    assert validate(m) == ["vitals.ppg[7]: NaN and infinity are not allowed"]


def test_many_bad_signal_entries_are_summarised(example):
    m = example("vitals")
    m["abp"] = ["x"] * 125
    errors = validate(m)
    assert len(errors) == 4
    assert errors[-1] == "vitals.abp: 122 more invalid entries"


def test_signal_not_a_list_fails(example):
    m = example("vitals")
    m["ecg"] = "0,1,2"
    assert has_error(validate(m), "vitals.ecg: expected null or a list of 125 numbers")


def test_fs_must_be_125(example):
    m = example("vitals")
    m["fs"] = 250
    assert validate(m) == ["vitals.fs: expected 125, got 250"]


def test_seq_and_ts_must_be_integers(example):
    m = example("vitals")
    m["seq"] = 18452.0
    m["ts"] = 1792252800000.0
    errors = validate(m)
    assert "vitals.seq: expected integer, got float" in errors
    assert "vitals.ts: expected integer, got float" in errors


def test_seq_negative_fails(example):
    m = example("vitals")
    m["seq"] = -1
    assert validate(m) == ["vitals.seq: must be >= 0, got -1"]


def test_nibp_null_is_valid_and_partial_fails(example):
    m = example("vitals")
    m["nibp"] = None
    assert validate(m) == []
    m["nibp"] = {"sys": 118, "dia": 72, "ts": 1792252790000}
    assert validate(m) == ["vitals.nibp.map: required field is missing"]


def test_nibp_ts_must_be_integer(example):
    m = example("vitals")
    m["nibp"]["ts"] = 1792252790000.5
    assert validate(m) == ["vitals.nibp.ts: expected integer, got float"]


def test_monitor_alarm_rules(example):
    m = example("vitals")
    m["monitor_alarm"] = None
    assert validate(m) == []
    m["monitor_alarm"] = {"code": "AFIB", "priority": "high"}
    assert has_error(validate(m), "vitals.monitor_alarm.code: expected one of ASYSTOLE")
    m["monitor_alarm"] = {"code": "VFIB", "priority": "none"}
    assert has_error(validate(m), "vitals.monitor_alarm.priority")


def test_device_must_belong_to_bed(example):
    m = example("vitals")
    m["device_id"] = "MON-04"
    assert has_error(validate(m), "vitals.device_id", "does not belong to bed_id 'B03'")


def test_missing_field_is_an_error_not_a_default(example):
    m = example("vitals")
    del m["hr"]
    assert validate(m) == ["vitals.hr: required field is missing"]


# --------------------------------------------------------------------------- IDs

@pytest.mark.parametrize("bed", ["B01", "B12", "B13", "B99"])
def test_two_digit_bed_ids_pass(example, bed):
    m = example("bedside_check")
    m["bed_id"] = bed
    assert validate(m) == []


@pytest.mark.parametrize("bed", ["B00", "B3", "B003", "B0003", "b03", "B03 ", "B٠٣", 3, None])
def test_bad_bed_ids_fail(example, bed):
    m = example("bedside_check")
    m["bed_id"] = bed
    assert has_error(validate(m), "bedside_check.bed_id")


@pytest.mark.parametrize("dev", ["MON-00", "MON-3", "MON-0003", "MON03", "mon-03"])
def test_bad_device_ids_fail(example, dev):
    m = example("net_features")
    m["device_id"] = dev
    assert has_error(validate(m), "net_features.device_id")


def test_device_bed_mapping():
    assert device_for_bed("B03") == "MON-03"
    assert bed_for_device("MON-12") == "B12"
    assert BED_IDS == tuple(f"B{i:02d}" for i in range(1, 13))
    for bad in ("B0003", "B00", "X"):
        with pytest.raises(ValueError, match="device_for_bed"):
            device_for_bed(bad)
    with pytest.raises(ValueError, match="bed_for_device"):
        bed_for_device("MON-0003")


# --------------------------------------------------------------------------- 3. verdict priority

def test_tampering_with_high_priority_fails(example):
    m = example("verdict")
    m["priority"] = "high"
    assert validate(m) == ["verdict.priority: verdict TAMPERING requires priority 'medium', got 'high'"]


def test_device_attack_with_none_priority_passes(example):
    m = example("verdict")
    m["verdict"], m["priority"] = "DEVICE_ATTACK", "none"
    assert validate(m) == []


@pytest.mark.parametrize("verdict,priority", sorted(VERDICT_PRIORITY.items()))
def test_every_verdict_priority_pair_passes(example, verdict, priority):
    m = example("verdict")
    m["verdict"], m["priority"] = verdict, priority
    assert validate(m) == []


def test_verdict_scores_rules(example):
    m = example("verdict")
    m["scores"] = {"M1": 0, "M4": 1}  # some models missing; 0 and 1 are in range
    assert validate(m) == []
    m["scores"] = {"M7": 0.5, "M2": 1.5}
    errors = validate(m)
    assert has_error(errors, "verdict.scores", "unknown model key 'M7'")
    assert "verdict.scores.M2: expected a number from 0 to 1, got 1.5" in errors


def test_confidence_and_trust_range(example):
    m = example("verdict")
    m["confidence"], m["trust"] = 0, 1
    assert validate(m) == []
    m["confidence"], m["trust"] = -0.1, NAN
    errors = validate(m)
    assert "verdict.confidence: expected a number from 0 to 1, got -0.1" in errors
    assert "verdict.trust: NaN and infinity are not allowed" in errors


def test_last_trusted_ts_may_be_null(example):
    m = example("verdict")
    m["last_trusted_ts"] = None
    assert validate(m) == []


# --------------------------------------------------------------------------- 4. action allow-list

def test_disable_client_by_a1_fails(example):
    m = example("action")
    m["by"] = "A1"
    errors = validate(m)
    assert len(errors) == 1
    assert errors[0].startswith("action.action: 'disable_client' is not allowed for A1 (allowed: ")


def test_disable_client_by_a2_passes(example):
    assert validate(example("action")) == []


def test_undo_by_staff_passes(example):
    m = example("action")
    m.update(by="staff:priya", action="undo", undoes="act_000231", action_id="act_000232", undo_id=None)
    assert validate(m) == []


def test_undo_without_undoes_fails(example):
    m = example("action")
    m.update(by="staff:priya", action="undo", undoes=None)
    assert validate(m) == ["action.undoes: an 'undo' action must name the original action_id in undoes"]


def test_every_allowed_pair_passes_and_a9_has_none(example):
    for actor, actions in ALLOWED_ACTIONS.items():
        for act in actions:
            m = example("action")
            m.update(by="staff:sam" if actor == "staff" else actor, action=act, bed_id=None, device_id=None,
                     undoes="act_1" if act == "undo" else None)
            assert validate(m) == [], (actor, act)
    m = example("action")
    m["by"] = "A9"
    assert has_error(validate(m), "is not allowed for A9 (allowed: nothing)")


@pytest.mark.parametrize("by", ["A0", "A10", "staff:", "staff: x", "priya", None])
def test_bad_actor_fails(example, by):
    m = example("action")
    m["by"] = by
    assert has_error(validate(m), "action.by")


def test_action_nullable_fields(example):
    m = example("action")
    m.update(bed_id=None, device_id=None, undo_id=None, undoes=None, approved_by=None)
    assert validate(m) == []


# --------------------------------------------------------------------------- 5. lengths and windows

def test_reason_of_121_chars_fails_and_120_passes(example):
    m = example("score")
    m["reason"] = "x" * 121
    assert validate(m) == ["score.reason: at most 120 characters, got 121"]
    m["reason"] = "x" * 120
    assert validate(m) == []


def test_four_reasons_in_a_verdict_fail(example):
    m = example("verdict")
    m["reasons"] = ["a", "b", "c", "d"]
    assert validate(m) == ["verdict.reasons: at most 3 reasons, got 4"]


@pytest.mark.parametrize("mtype", ["score", "verdict", "net_features"])
def test_window_start_not_multiple_of_5000_fails(example, mtype):
    m = example(mtype)
    m["window_start"] = 1792252796000
    assert validate(m) == [f"{mtype}.window_start: must be a multiple of 5000 ms, got 1792252796000"]


def test_score_range_and_zero(example):
    m = example("score")
    m["score"] = 0
    assert validate(m) == []
    m["score"] = 1.01
    assert validate(m) == ["score.score: expected a number from 0 to 1, got 1.01"]


def test_score_model_and_extra(example):
    m = example("score")
    m["model"] = "M7"
    m["extra"] = {"ptt_ms": NAN}
    errors = validate(m)
    assert has_error(errors, "score.model: expected a model ID M1..M6")
    assert "score.extra.ptt_ms: NaN and infinity are not allowed" in errors
    m = example("score")
    m["extra"] = None
    assert validate(m) == ["score.extra: expected an object, got null"]


# --------------------------------------------------------------------------- other types

def test_alert_rules(example):
    m = example("alert")
    m.update(ladder_step=4, status="snoozed")
    errors = validate(m)
    assert "alert.ladder_step: expected an integer from 1 to 3, got 4" in errors
    assert has_error(errors, "alert.status: expected one of open, acked, escalated, closed")
    m = example("alert")
    m.update(status="acked", acked_by="staff:priya", acked_ts=1792252809000)
    assert validate(m) == []


def test_bedside_check_rules(example):
    m = example("bedside_check")
    m.update(result="patient_fine", by="A1")
    errors = validate(m)
    assert has_error(errors, "bedside_check.result")
    assert has_error(errors, "bedside_check.by: expected 'staff:<name>'")


def test_net_features_extra_fields_always_allowed(example):
    m = example("net_features")
    m["retrans_per_s"] = 0.25
    assert validate(m) == []
    assert validate(m, strict=True) == []
    m["retrans_per_s"] = INF
    assert validate(m) == ["net_features.retrans_per_s: NaN and infinity are not allowed"]


def test_net_features_null_means_missing(example):
    m = example("net_features")
    m["iat_std_ms"] = None
    assert validate(m) == []


def test_request_rules(example):
    m = example("request")
    m["bed_id"] = None
    assert validate(m) == []
    m.update(action="isolate_device", target_id="al_0042")
    assert has_error(validate(m), "request.target_id: isolate_device needs a device ID")
    m["target_id"] = "MON-07"
    assert validate(m) == []
    m["action"] = "reboot"
    assert has_error(validate(m), "request.action: expected one of ack_alert")


def test_demo_control_rules(example):
    m = example("demo_control")
    m.update(cmd="reset", start_at_s=600)
    assert validate(m) == []
    m.update(cmd="pause", start_at_s=-1)
    errors = validate(m)
    assert has_error(errors, "demo_control.cmd")
    assert "demo_control.start_at_s: must be >= 0, got -1" in errors
    m.update(cmd="run", start_at_s=1.5)
    assert validate(m) == ["demo_control.start_at_s: expected integer, got float"]


def test_record_rules(example):
    m = example("record")
    m["data"] = {"nested": [1, {"x": NAN}]}
    assert validate(m) == ["record.data.nested[1].x: NaN and infinity are not allowed"]
    m["data"] = {"s": {1, 2}}
    assert validate(m) == ["record.data.s: a value of type set cannot be sent as JSON"]
    m["data"] = {}
    m["kind"] = "memo"
    assert has_error(validate(m), "record.kind: expected one of ticket, report, incident, briefing, workload")


# --------------------------------------------------------------------------- strict mode, envelope

def test_extra_keys_allowed_by_default_and_flagged_in_strict(example):
    m = example("alert")
    m["channel"] = "sms"
    assert validate(m) == []
    assert validate(m, strict=True) == ["alert.channel: unknown field (strict mode)"]


def test_strict_mode_checks_nested_objects(example):
    m = example("vitals")
    m["nibp"]["cuff"] = "left"
    assert validate(m) == []
    assert validate(m, strict=True) == ["vitals.nibp.cuff: unknown field (strict mode)"]


def test_extra_key_with_nan_fails_even_when_not_strict(example):
    m = example("verdict")
    m["debug"] = [1.0, NAN]
    assert validate(m) == ["verdict.debug[1]: NaN and infinity are not allowed"]


def test_envelope_errors():
    assert validate([]) == ["message: expected a JSON object, got list"]
    assert validate({}) == ["message.type: required field is missing", "message.v: required field is missing"]
    assert validate({"v": 1, "type": "gossip"})[0].startswith("message.type: expected one of vitals")
    errors = validate({**EXAMPLES["record"], "v": 2})
    assert errors == ["record.v: expected 1, got 2"]
    assert validate({**EXAMPLES["record"], "v": True}) == ["record.v: expected 1, got True"]


JUNK = [None, True, -1, 0, 1.5, NAN, INF, "", "x" * 500, [], [None], {}, {"a": NAN}, {1, 2}, b"x", object()]


@pytest.mark.parametrize("mtype", MESSAGE_TYPES)
def test_validate_never_raises_on_junk_field_values(example, mtype):
    for key in list(EXAMPLES[mtype]):
        for junk in JUNK:
            m = example(mtype)
            m[key] = junk
            assert isinstance(validate(m), list)
            assert isinstance(validate(m, strict=True), list)


# --------------------------------------------------------------------------- builders

def test_builders_produce_valid_messages(example):
    t = 1792252800000
    built = {
        "vitals": make_vitals(bed_id="B03", seq=18452, ts=t, ecg=ECG, ppg=PPG, abp=ABP, hr=82, spo2=97, rr=16,
                              nibp={"sys": 118, "dia": 72, "map": 87, "ts": 1792252790000},
                              monitor_alarm={"code": "VTACH", "priority": "high"}),
        "score": make_score(**{k: v for k, v in example("score").items() if k not in ("v", "type")}),
        "verdict": make_verdict(**{k: v for k, v in example("verdict").items() if k not in ("v", "type")}),
        "action": make_action(**{k: v for k, v in example("action").items() if k not in ("v", "type")}),
        "alert": make_alert(**{k: v for k, v in example("alert").items() if k not in ("v", "type")}),
        "bedside_check": make_bedside_check(bed_id="B07", ts=1792252860000, result="patient_ok", by="staff:priya"),
        "net_features": make_net_features(**{k: v for k, v in example("net_features").items()
                                             if k not in ("v", "type")}),
        "request": make_request(**{k: v for k, v in example("request").items() if k not in ("v", "type")}),
        "demo_control": make_demo_control(cmd="run", run_id="run_20261017_160000", ts=t),
        "record": make_record(kind="ticket", record_id="tk_0007", by="A6", data={"any": "JSON object"},
                              ts=1792252806000),
    }
    for mtype, msg in built.items():
        assert validate(msg, strict=True) == [], mtype
    assert built["vitals"] == example("vitals")
    assert built["record"] == example("record")
    assert list(built["action"]) == list(example("action"))  # same field order as the contract


def test_builders_fill_ts_and_defaults():
    before = now_ms()
    v = make_vitals(bed_id="B05", seq=0)
    after = now_ms()
    assert type(v["ts"]) is int and before <= v["ts"] <= after
    assert v["device_id"] == "MON-05"
    assert v["hr"] is None and v["ecg"] is None and v["nibp"] is None
    assert validate(v) == []
    verdict = make_verdict(bed_id="B01", window_start=1792252795000, verdict="LOOSE_SENSOR", confidence=0.6,
                           trust=0.9, scores={"M1": 0.8})
    assert verdict["priority"] == "low" and verdict["reasons"] == [] and validate(verdict) == []
    alert = make_alert(alert_id="al_1", bed_id="B01", verdict="EMERGENCY", text="Go now.", to=["staff:priya"])
    assert alert["priority"] == "high" and alert["status"] == "open" and validate(alert) == []


def test_score_and_net_features_have_no_ts():
    s = make_score(bed_id="B03", model="M2", model_version="m2", window_start=0, score=0.0, label="ok",
                   reason="")
    assert "ts" not in s and s["extra"] == {} and validate(s) == []


def test_builders_accept_extra_fields_but_not_envelope():
    n = make_net_features(device_id="MON-01", window_start=0, msgs_per_s=1, bytes_per_s=1, iat_mean_ms=1,
                          iat_std_ms=0, payload_mean=1, payload_std=0, senders=1, connects_per_s=0, malformed=0,
                          seq_gaps=0, seq_repeats=0, stale_ms=0, tls_errors=0)
    assert n["tls_errors"] == 0 and validate(n, strict=True) == []
    with pytest.raises(ValueError, match="set by the builder"):
        make_record(kind="ticket", record_id="t", by="A6", data={}, v=2)


# --------------------------------------------------------------------------- 6. encode

def test_encode_turns_nan_into_null(example):
    m = example("vitals")
    m["hr"] = NAN
    m["ecg"][0] = NAN
    m["abp"][5] = INF
    raw = encode(m)
    assert b"NaN" not in raw and b"Infinity" not in raw
    back = json.loads(raw)
    assert back["hr"] is None and back["ecg"][0] is None and back["abp"][5] is None
    assert math.isnan(m["hr"])  # the caller's message is not modified


def test_encode_is_compact_utf8(example):
    raw = encode(example("alert"))
    assert b", " not in raw and b": " not in raw
    assert "Bed 3 — possible".encode("utf-8") in raw
    assert json.loads(raw.decode("utf-8")) == example("alert")


def test_encode_refuses_invalid_message(example):
    m = example("verdict")
    m["priority"] = "high"
    with pytest.raises(MessageError) as info:
        encode(m)
    assert info.value.errors == ["verdict.priority: verdict TAMPERING requires priority 'medium', got 'high'"]
    assert "verdict.priority" in str(info.value)
    assert isinstance(info.value, ValueError)


def test_encode_check_false_skips_validation(example):
    m = example("verdict")
    m["priority"] = "high"
    assert json.loads(encode(m, check=False))["priority"] == "high"
    with pytest.raises(MessageError, match="cannot be encoded as JSON"):
        encode({"v": 1, "type": "record", "data": {1, 2}}, check=False)


def test_encode_strict(example):
    m = example("record")
    m["note"] = "x"
    encode(m)
    with pytest.raises(MessageError, match="unknown field"):
        encode(m, strict=True)


def test_encode_tuples_become_lists(example):
    m = example("verdict")
    m["reasons"] = ("a", "b")
    assert json.loads(encode(m))["reasons"] == ["a", "b"]


# --------------------------------------------------------------------------- 7. decode

@pytest.mark.parametrize("raw", [
    b"", b"\xff\xfe\x00garbage", b"not json", b"{", b"[1, 2, 3]", b"42", b'"text"', b"null",
    b'{"v": 1, "type": "vitals", "hr": NaN}', b'{"x": Infinity}', b"[" * 100_000, b"1" * 10_000,
    bytearray(b"\x00\x01"), memoryview(b"{}"), None, 12, "{bad",
])
def test_decode_garbage_returns_errors_and_never_raises(raw):
    message, errors = decode(raw)
    assert errors, raw
    assert all(isinstance(e, str) for e in errors)
    assert message is None or isinstance(message, dict)


def test_decode_valid_round_trip(example):
    for mtype in MESSAGE_TYPES:
        message, errors = decode(encode(example(mtype)))
        assert errors == [] and message == example(mtype)


def test_decode_returns_invalid_object_with_errors(example):
    m = example("score")
    m["score"] = 2
    message, errors = decode(json.dumps(m).encode())
    assert message == m
    assert errors == ["score.score: expected a number from 0 to 1, got 2"]


def test_decode_rejects_overflowing_numbers():
    raw = json.dumps(EXAMPLES["verdict"]).replace("0.88", "1e999").encode()
    message, errors = decode(raw)
    assert errors == ["verdict.confidence: NaN and infinity are not allowed"]


def test_decode_reports_bad_utf8():
    message, errors = decode(b'{"v": 1, "type": "\xff"}')
    assert message is None and errors[0].startswith("message: not valid UTF-8")


def test_decode_strict(example):
    m = example("demo_control")
    m["who"] = "me"
    raw = encode(m)
    assert decode(raw)[1] == []
    assert decode(raw, strict=True)[1] == ["demo_control.who: unknown field (strict mode)"]


# --------------------------------------------------------------------------- constants

def test_constants():
    assert VERDICT_PRIORITY["DEVICE_ATTACK"] == "none" and len(VERDICT_PRIORITY) == 8
    assert set(MODEL_MEANING) == {"M1", "M2", "M3", "M4", "M5", "M6"}
    assert "undo" in ALLOWED_ACTIONS["staff"] and ALLOWED_ACTIONS["A9"] == frozenset()


# --------------------------------------------------------------------------- performance

def test_validate_vitals_under_1ms(example):
    m = example("vitals")
    validate(m)  # warm up
    samples = []
    for _ in range(1000):
        start = time.perf_counter()
        validate(m)
        samples.append(time.perf_counter() - start)
    median_ms = statistics.median(samples) * 1000
    assert median_ms < 1.0, f"validate(vitals) median {median_ms:.3f} ms"


# ---- v1.3: optional second ECG lead (ecg2 + ecg_leads); addition only

def test_vitals_without_ecg2_is_still_valid_strict(example):
    m = example("vitals")
    assert "ecg2" not in m and validate(m, strict=True) == []


def test_ecg2_and_leads_are_valid_and_known_in_strict(example):
    m = example("vitals")
    m["ecg2"] = list(ECG)
    m["ecg_leads"] = ["II", "V"]
    assert validate(m) == []
    assert validate(m, strict=True) == []


def test_ecg2_null_and_null_entries_are_valid(example):
    m = example("vitals")
    m["ecg2"] = None
    m["ecg_leads"] = ["II"]
    assert validate(m, strict=True) == []
    m["ecg2"] = [None] * 60 + list(ECG[60:])
    assert validate(m) == []


def test_ecg2_wrong_length_nan_and_type_fail(example):
    m = example("vitals")
    m["ecg2"] = ECG[:124]
    assert validate(m) == ["vitals.ecg2: expected 125 entries, got 124"]
    m["ecg2"] = list(ECG)
    m["ecg2"][7] = NAN
    errs = validate(m)
    assert len(errs) == 1 and errs[0].startswith("vitals.ecg2[7]")
    m["ecg2"] = "II"
    assert validate(m) and validate(m)[0].startswith("vitals.ecg2:")


def test_ecg_leads_rules(example):
    m = example("vitals")
    m["ecg_leads"] = None
    assert validate(m) == []
    for bad in ("II", ["II", ""], ["II", 5], {"0": "II"}):
        m["ecg_leads"] = bad
        assert validate(m), bad


def test_ecg2_round_trips_encode_decode(example):
    m = example("vitals")
    m["ecg2"] = [NAN] + list(ECG[1:])
    m["ecg_leads"] = ["II", "V"]
    obj, errs = decode(encode(m, strict=True), strict=True)
    assert errs == [] and obj["ecg2"][0] is None and obj["ecg_leads"] == ["II", "V"]


def test_make_vitals_passes_ecg2_through():
    m = make_vitals(bed_id="B03", seq=1, ts=1, ecg=list(ECG), ecg2=list(ECG), ecg_leads=["II", "V"])
    assert m["ecg2"] == list(ECG) and validate(m, strict=True) == []
