"""Safety regressions for the in-memory state; no broker or database required."""
import pytest

from sw_api.config import BedConfig, WardConfig
from sw_api.state import BUFFER_S, WardState, point_from_row


class FakeClock:
    def __init__(self):
        self.now = 100_000
        self.elapsed = 100.0

    def ms(self):
        return self.now

    def mono(self):
        return self.elapsed


@pytest.fixture
def state():
    ward = WardConfig("Test", (BedConfig("B01", "MON-01", None, "A.K.", 67, "F"),), ("B01",))
    return WardState(ward, FakeClock())


def vital(ts, hr=70, **extras):
    return {"bed_id": "B01", "device_id": "MON-01", "ts": ts, "seq": ts // 1000,
            "hr": hr, "spo2": 98, "rr": 14, "ecg": [1.0] * 125, "ppg": None,
            "abp": None, **extras}


def verdict(ts, last_trusted_ts=None, value="NORMAL"):
    return {"bed_id": "B01", "ts": ts, "verdict": value, "last_trusted_ts": last_trusted_ts,
            "priority": "none", "trust": 1.0, "reasons": []}


def action(aid, ts, kind="disable_client", **extras):
    return {"action_id": aid, "ts": ts, "action": kind, "device_id": "MON-01",
            "bed_id": "B01", "result": "ok", **extras}


def normal_points(state, timestamps):
    state.on_verdict(verdict(0))
    for ts in timestamps:
        state.on_vitals(vital(ts))


def test_missing_verdict_never_marks_monitor_values_trusted(state):
    point, _ = state.on_vitals(vital(1000))
    assert point.trusted is False
    assert state.view("B01").latest_trusted is False
    assert state.beds["B01"].verdict is None


def test_failed_undo_keeps_isolation_in_force(state):
    state.on_action(action("isolate", 2000))
    state.on_action(action("failed-undo", 3000, "enable_client", undoes="isolate", result="failed"))
    assert state.device_brief("MON-01")["isolated_since"] == 2000


@pytest.mark.parametrize("isolation, cutoff, expected", [(2500, 4000, 2000), (4500, 3000, 3000), (3000, 3000, 2000)])
def test_earliest_isolation_or_verdict_boundary_wins(state, isolation, cutoff, expected):
    normal_points(state, [1000, 2000, 3000, 4000, 5000])
    state.on_action(action("isolate", isolation))
    state.on_verdict(verdict(6000, cutoff, "TAMPERING"))
    assert state.view("B01").latest["ts"] == expected


def test_pin_skips_points_that_were_never_trusted(state):
    state.on_vitals(vital(1000, 55))
    state.on_verdict(verdict(1500))
    state.on_vitals(vital(2000, 60))
    state.on_verdict(verdict(2500, 2000, "UNSURE"))
    state.on_vitals(vital(3000, 160))
    state.on_verdict(verdict(4000, 3000, "TAMPERING"))
    assert state.view("B01").latest["hr"] == 60
    assert state.take_pin_lookups() == []


def test_database_pin_cannot_fabricate_trust(state):
    state.on_vitals(vital(5000))
    state.on_verdict(verdict(6000, 2000, "TAMPERING"))
    state.view("B01")
    state.take_pin_lookups()
    bad = point_from_row({"ts": 2000, "hr": 30, "trusted": False}, None)
    state.set_pin("B01", 2000, True, bad)
    view = state.view("B01")
    assert view.latest["hr"] == 70
    assert view.latest_trusted is False


def test_missing_persisted_trust_defaults_to_untrusted():
    assert point_from_row({"ts": 1000}, None).trusted is False


def test_duplicate_seconds_do_not_shrink_thirty_minute_retention(state):
    normal_points(state, range(1000, (BUFFER_S + 1) * 1000, 1000))
    for offset in range(1, 101):
        state.on_vitals(vital(BUFFER_S * 1000 + offset, offset))
    assert len(state.beds["B01"].points) == BUFFER_S
    assert state.buffer_start("B01") == 1000
    assert state.history("B01", 0)[-1]["hr"] == 100


def test_older_same_second_message_cannot_replace_newer_values(state):
    normal_points(state, [1900, 2900])
    state.on_vitals(vital(1100, 200))
    assert len(state.beds["B01"].points) == 2
    assert state.history("B01", 0)[0]["ts"] == 1900


def test_late_new_cuff_is_carried_to_following_points(state):
    normal_points(state, [1000, 3000])
    state.on_vitals(vital(2000, nibp={"sys": 120, "dia": 75, "map": 90, "ts": 2000}))
    assert state.view("B01").latest["bp"]["sys"] == 120


def test_trust_mark_covers_database_when_ram_has_no_trusted_point(state):
    state.on_vitals(vital(10_000))
    _, mark = state.on_verdict(verdict(20_000, 1000, "TAMPERING"))
    assert (mark.after_ts, mark.upto_ts) == (1000, 20_000)


def test_waveform_matches_exact_frozen_point_and_survives_cache_eviction(state):
    normal_points(state, [1000])
    state.on_verdict(verdict(2000, 1000, "TAMPERING"))
    assert state.waveform("B01", trusted=True) == {"ecg": [1.0] * 25, "ppg": [], "abp": []}
    for ts in range(3000, 103_000, 1000):
        state.on_vitals(vital(ts, ecg=[9.0] * 125))
    assert len(state.beds["B01"].thin_waves) <= 60
    assert state.waveform("B01", 1000, trusted=True)["ecg"] == [1.0] * 25
    assert state.waveform("B01", 2000) == {"ecg": [], "ppg": [], "abp": []}


def test_untrusted_waveform_is_not_returned_as_trusted(state):
    state.on_vitals(vital(1000))
    assert state.waveform("B01", 1000, trusted=True) == {"ecg": [], "ppg": [], "abp": []}


def test_offline_keeps_trusted_pin_without_freshness_from_wall_clock(state):
    normal_points(state, [1000, 2000])
    state.on_verdict(verdict(3000, 1000, "TAMPERING"))
    state.clock.elapsed += 6
    state.clock.now -= 50_000
    view = state.view("B01")
    assert view.display == "offline"
    assert view.latest["ts"] == 1000


def test_manual_values_do_not_replace_monitor_zero(state):
    normal_points(state, [1000])
    state.on_vitals(vital(2000, 0))
    state.add_manual({"bed_id": "B01", "ts": 3000, "hr": 80})
    assert state.view("B01").latest["hr"] == 0


def test_agent_record_equal_timestamp_replacement_keeps_version_audit_order(state):
    original = {"record_id": "R1", "kind": "ticket", "ts": 1000, "by": "A6", "data": {"status": "open"}}
    state.on_record(original)
    state.patch_record("R1", {"status": "resolved"}, "staff:tom")
    replacement = state.on_record({**original, "data": {"status": "in_progress"}})
    assert replacement["version"] == 3
    assert replacement["data"]["status"] == "in_progress"


def test_late_point_from_recovered_untrusted_interval_never_becomes_pin(state):
    normal_points(state, [1000])
    state.on_verdict(verdict(5000, 1000, "TAMPERING"))
    state.on_verdict(verdict(10_000))
    point, _ = state.on_vitals(vital(3000, 900))
    assert point.trusted is False
    state.on_verdict(verdict(15_000, 4000, "TAMPERING"))
    assert state.view("B01").latest["hr"] == 70


def test_late_replacement_during_past_untrusted_interval_stays_untrusted(state):
    normal_points(state, [1000])
    state.on_verdict(verdict(5000, 1000, "TAMPERING"))
    state.on_vitals(vital(3000, 900))
    state.on_verdict(verdict(10_000))
    point, _ = state.on_vitals(vital(3100, 901))
    assert point.trusted is False
    assert state.history("B01", 0)[-1]["trusted"] is False


@pytest.mark.parametrize("ts, expected", [(1000, True), (9999, False), (10_000, True), (10_001, True)])
def test_recovered_interval_excludes_new_recovery_timestamp(state, ts, expected):
    normal_points(state, [])
    state.on_verdict(verdict(5000, 1000, "TAMPERING"))
    state.on_verdict(verdict(10_000, value="EMERGENCY"))
    point, _ = state.on_vitals(vital(ts))
    assert point.trusted is expected


def test_intervals_merge_without_poisoning_trusted_gap(state):
    normal_points(state, [])
    state.on_verdict(verdict(5000, 1000, "TAMPERING"))
    state.on_verdict(verdict(10_000))
    state.on_verdict(verdict(15_000, 12_000, "TAMPERING"))
    state.on_verdict(verdict(20_000))
    point, _ = state.on_vitals(vital(11_000))
    assert point.trusted is True
    point, _ = state.on_vitals(vital(17_000))
    assert point.trusted is False
    # A new backward cutoff overlaps both previous intervals; that gap becomes untrusted too.
    state.on_verdict(verdict(25_000, 2000, "TAMPERING"))
    state.on_verdict(verdict(30_000))
    point, _ = state.on_vitals(vital(11_100))
    assert point.trusted is False


def test_isolation_history_remains_untrusted_after_undo_and_verdict_recovery(state):
    normal_points(state, [])
    state.on_action(action("isolate", 2000))
    state.on_verdict(verdict(5000, 3000, "TAMPERING"))
    state.on_verdict(verdict(10_000))
    state.on_action(action("undo", 12_000, "undo", undoes="isolate"))
    point, _ = state.on_vitals(vital(11_000))
    assert point.trusted is False
    point, _ = state.on_vitals(vital(12_001))
    assert point.trusted is True


def test_future_point_seen_while_untrusted_cannot_gain_trust_on_replacement(state):
    normal_points(state, [])
    state.on_verdict(verdict(5000, 1000, "TAMPERING"))
    state.on_vitals(vital(20_000, 900))
    state.on_verdict(verdict(10_000))
    point, _ = state.on_vitals(vital(20_000, 901, seq=100))
    assert point.trusted is False


def test_undo_without_device_identity_closes_original_bed_trust_interval(state):
    normal_points(state, [])
    state.on_action(action("isolate", 2000))
    state.on_action(action("undo", 5000, "undo", undoes="isolate", device_id=None, bed_id=None))
    old_point, _ = state.on_vitals(vital(3000))
    fresh_point, _ = state.on_vitals(vital(6000))
    assert old_point.trusted is False
    assert fresh_point.trusted is True


def test_persisted_pin_cannot_override_known_historical_untrusted_interval(state):
    normal_points(state, [1000])
    state.on_verdict(verdict(5000, 1000, "TAMPERING"))
    state.on_verdict(verdict(10_000))
    state.on_verdict(verdict(15_000, 4000, "TAMPERING"))
    bad = point_from_row({"ts": 3000, "hr": 900, "trusted": True}, None)
    state.set_pin("B01", 4000, True, bad)
    assert state.view("B01").latest["hr"] == 70
