"""Invalid messages and publish failures; the scale command; the CLI; the script and pack loaders."""

from __future__ import annotations

import json
import os

import numpy as np
import pytest
import sw_common

import sw_sim.engine as engine
from conftest import SCRIPT_PATH, FakeBus, FakeClock, play, read_events, write_pack
from sw_sim.__main__ import main
from sw_sim.config import ScriptError, load_env, parse_script
from sw_sim.engine import WardRun, to_int
from sw_sim.packs import PackError, load_pack
from sw_sim.scale import MAX_SCALE_BEDS, build_scale_script, run_scale


# ---------------------------------------------------------------- invalid / failed messages

def test_invalid_message_is_skipped_and_seq_has_no_gap(script, packs, tmp_path, monkeypatch, caplog):
    real_validate = sw_common.validate

    def validate(message):
        if message["bed_id"] == "B01" and message["ts"] % 7000 == 0:
            return ["forced failure for the test"]
        return real_validate(message)

    monkeypatch.setattr(engine.sw_common, "validate", validate)
    result, bus, events, _ = play(script.select(["B01", "B02"]), packs, tmp_path)
    b01 = bus.by_bed()["B01"]
    assert result.invalid > 0
    assert len(b01) == 1200 - result.invalid
    assert all(m["ts"] % 7000 != 0 for m in b01)
    assert [m["seq"] for m in b01] == list(range(1, len(b01) + 1))
    assert len(bus.by_bed()["B02"]) == 1200
    assert "forced failure for the test" in caplog.text
    assert events[-1]["detail"]["invalid"] == result.invalid


def test_publish_failure_is_counted_not_fatal(script, packs, tmp_path):
    bus = FakeBus(fail_for=lambda m: m["bed_id"] == "B02" and m["seq"] == 5)
    result, bus, _, _ = play(script.select(["B01", "B02"]), packs, tmp_path, bus=bus)
    assert result.publish_errors >= 1
    seqs = [m["seq"] for m in bus.by_bed()["B02"]]
    assert seqs == list(range(1, len(seqs) + 1))


def test_dropped_publish_is_counted(script, packs, tmp_path):
    clock = FakeClock(start_ms=1_792_252_800_000.0)
    origin = 1_792_252_801_000                      # next whole second + lead_ms
    dropped_ts = {origin + k * 1000 for k in (100, 101, 102)}
    bus = FakeBus(drop_for=lambda m: m["bed_id"] == "B01" and m["ts"] in dropped_ts)
    result, bus, events, _ = play(script.select(["B01"]), packs, tmp_path, bus=bus, clock=clock)
    assert result.origin_ms == origin
    seqs = [m["seq"] for m in bus.messages]
    assert seqs == list(range(1, 1198))             # a dropped message's seq is reused, no gap
    assert result.publish_errors == 3 and result.sent == 1197
    assert events[-1]["detail"]["publish_errors"] == 3
    rows = (result.run_dir / "sent.csv").read_text().splitlines()[1:]
    assert sum(int(r.split(",")[1]) for r in rows) == 1197


def test_to_int():
    assert to_int(0.0) == 0 and to_int(82.4) == 82 and to_int(82.5) == 83
    assert to_int(float("nan")) is None and to_int(float("inf")) is None and to_int(None) is None


# ---------------------------------------------------------------- scale

def test_scale_ids_offsets_and_report(script, packs, tmp_path):
    bus = FakeBus()
    report = run_scale(script, packs, n_beds=8, seconds=20, run_id="scale_test", runs_dir=tmp_path,
                       clock=FakeClock(), bus=bus)
    by_bed = bus.by_bed()
    assert sorted(by_bed) == [f"B{n}" for n in range(13, 21)]
    assert {m["device_id"] for m in bus.messages} == {f"MON-{n}" for n in range(13, 21)}
    assert all(len(v) == 20 for v in by_bed.values())
    assert bus.validation_errors == []
    assert all(m["monitor_alarm"] is None for m in bus.messages)
    assert report.messages_sent == report.messages_expected == 160
    assert report.messages_on_time == 160 and report.on_time_per_s_min == 8
    saved = json.loads((tmp_path / "scale_test" / "report.json").read_text())
    assert saved["messages_on_time"] == 160
    # copies of the same pack start at different pack seconds
    s = build_scale_script(script, packs, 87, 60)
    assert s.beds[0].bed_id == "B13" and s.beds[-1].bed_id == "B99" and s.beds[-1].device_id == "MON-99"
    starts = {(b.pack, b.pack_start_s) for b in s.beds}
    assert len(starts) == 87
    assert s.drift is None


@pytest.mark.parametrize("n", [0, MAX_SCALE_BEDS + 1])
def test_scale_cap(script, packs, n):
    with pytest.raises(ValueError):
        build_scale_script(script, packs, n, 10)


def test_scale_first_bed_one_covers_b01_to_b96(script, packs, tmp_path):
    s = build_scale_script(script, packs, 96, 10, first_bed=1)
    assert [b.bed_id for b in s.beds] == [f"B{n:02d}" for n in range(1, 97)]
    assert all(b.device_id == "MON-" + b.bed_id[1:] and b.suppress_alarms for b in s.beds)
    assert len({(b.pack, b.pack_start_s) for b in s.beds}) == 96
    bus = FakeBus()
    report = run_scale(script, packs, n_beds=3, seconds=5, run_id="scale_first", runs_dir=tmp_path,
                       clock=FakeClock(), bus=bus, first_bed=1)
    assert sorted(bus.by_bed()) == ["B01", "B02", "B03"] and bus.validation_errors == []
    assert report.messages_sent == 15


@pytest.mark.parametrize("first,n", [(0, 1), (100, 1), (1, 100), (90, 11)])
def test_scale_first_bed_stays_within_two_digit_ids(script, packs, first, n):
    with pytest.raises(ValueError):
        build_scale_script(script, packs, n, 10, first_bed=first)


def test_scale_loop_restarts_the_pack_and_keeps_counting(script, packs, tmp_path):
    name = build_scale_script(script, packs, 1, 10, first_bed=1).beds[0].pack
    length = packs[name].n_seconds
    assert not build_scale_script(script, packs, 1, 10).beds[0].loop_pack
    bus = FakeBus()
    report = run_scale(script, packs, n_beds=1, seconds=length + 3, run_id="scale_loop", runs_dir=tmp_path,
                       clock=FakeClock(), bus=bus, first_bed=1, loop=True)
    sent = bus.by_bed()["B01"]
    assert report.messages_sent == len(sent) == length + 3 and bus.validation_errors == []
    assert [m["seq"] for m in sent] == list(range(1, length + 4))
    assert all(b["ts"] - a["ts"] == 1000 for a, b in zip(sent, sent[1:]))
    assert sent[length]["ecg"] == sent[0]["ecg"] and sent[length + 2]["ppg"] == sent[2]["ppg"]


# ---------------------------------------------------------------- CLI

def test_cli_dry_run(packs_dir, tmp_path, capsys):
    code = main(["run", "--packs", str(packs_dir), "--script", str(SCRIPT_PATH), "--runs", str(tmp_path),
                 "--dry-run", "--start-at", "T+04:30", "--beds", "B03,B04,B08", "--run-id", "run_cli"])
    assert code == 0
    run_dir = tmp_path / "run_cli_dry"
    events = read_events(run_dir)
    assert events[0]["detail"]["dry_run"] is True and events[0]["detail"]["fast"] is True
    assert events[-1]["event"] == "run_end"
    assert {e["event"] for e in events} >= {"monitor_alarm", "drift_start", "source_end"}
    assert "complete" in capsys.readouterr().out


@pytest.mark.parametrize("args", [
    ["--beds", "B42"], ["--speed", "0.5"], ["--start-at", "T+20:00"], ["--start-at", "soon"], ["--run-id", "../x"],
])
def test_cli_rejects_bad_arguments(packs_dir, tmp_path, args):
    code = main(["run", "--packs", str(packs_dir), "--script", str(SCRIPT_PATH), "--runs", str(tmp_path),
                 "--dry-run", *args])
    assert code == 2


def test_cli_missing_packs(tmp_path):
    assert main(["run", "--packs", str(tmp_path), "--script", str(SCRIPT_PATH), "--dry-run"]) == 2


# ---------------------------------------------------------------- script, env, packs

def test_script_holds_the_ward_timing(script):
    assert script.run_length_s == 1200 and script.fs == 125
    joins = {b.bed_id: b.join_s for b in script.beds}
    assert joins == {**{f"B{n:02d}": 0 for n in range(1, 13)}, "B04": 90, "B07": 540}
    d = script.drift
    assert (d.bed_id, d.channel, d.ramp_start_s, d.ramp_end_s, d.hold_end_s, d.peak_mmHg) == ("B08", "abp", 300, 720, 900, 15.0)
    assert dict(script.rounding) == {"ecg": 3, "ppg": 2, "abp": 1}


def test_script_validation():
    base = {"run_length_s": 10, "fs": 125, "beds": [{"bed_id": "B01", "join_s": 0}]}
    assert parse_script(base).beds[0].pack_name == "B01"
    for bad in (
        {**base, "beds": []},
        {**base, "beds": [{"bed_id": "B01", "join_s": 10}]},
        {**base, "beds": [{"bed_id": "B01", "join_s": 0}, {"bed_id": "B01", "join_s": 1}]},
        {**base, "drift": {"bed_id": "B09", "ramp_start_s": 1, "ramp_end_s": 2, "hold_end_s": 3, "peak_mmHg": 1}},
        {**base, "drift": {"bed_id": "B01", "ramp_start_s": 5, "ramp_end_s": 2, "hold_end_s": 3, "peak_mmHg": 1}},
        {**base, "run_length_s": "1200"},
    ):
        with pytest.raises(ScriptError):
            parse_script(bad)


def test_bed_subset_keeps_drift_only_with_its_bed(script):
    assert script.select(["B01"]).drift is None
    assert script.select(["B08"]).drift is not None
    assert script.select(["B05", "B03"]).bed_ids() == ["B03", "B05"]   # script order kept
    with pytest.raises(ScriptError):
        script.select(["B42"])


def test_env_defaults_and_values():
    env = load_env({})
    assert (env.mqtt_host, env.mqtt_port, env.mqtt_user, env.mqtt_pass) == ("localhost", 1883, None, None)
    env = load_env({"MQTT_HOST": "hub", "MQTT_PORT": "8883", "MQTT_USER": "sim", "MQTT_PASS": "x",
                    "SW_PACKS": "/data/packs", "SW_RUNS": "/data/runs"})
    assert (env.mqtt_host, env.mqtt_port, str(env.packs_dir), str(env.runs_dir)) == ("hub", 8883, "/data/packs", "/data/runs")
    with pytest.raises(ValueError):
        load_env({"MQTT_PORT": "abc"})


def test_pack_endianness_and_partial_second(tmp_path):
    write_pack(tmp_path, "B01", 5)
    pack = load_pack(tmp_path, "B01")
    assert pack.waves["ecg"].dtype == np.float64 and pack.waves["ecg"].dtype.isnative
    raw = np.load(tmp_path / "B01.npz")["ecg"]
    assert raw.dtype.str == "<f4"
    assert np.array_equal(pack.waves["ecg"], raw.astype(np.float64))
    # cut the last half second of ecg: only 4 full seconds remain, never padded
    data = dict(np.load(tmp_path / "B01.npz"))
    data["ecg"] = data["ecg"][: 4 * 125 + 60]
    np.savez(tmp_path / "B01.npz", **data)
    assert load_pack(tmp_path, "B01").n_seconds == 4


def test_pack_bed_mismatch_rejected(script, tmp_path):
    write_pack(tmp_path, "B01", 5)
    meta = json.loads((tmp_path / "B01.json").read_text())
    meta["bed_id"] = "B02"
    (tmp_path / "B01.json").write_text(json.dumps(meta))
    pack = load_pack(tmp_path, "B01")
    with pytest.raises(PackError):
        WardRun(script.select(["B01"]), {"B01": pack}, run_id="r", runs_dir=tmp_path, clock=FakeClock(), bus=FakeBus())


def test_run_dir_never_overwritten(script, packs, tmp_path):
    first, _, _, _ = play(script.select(["B01"]), packs, tmp_path, run_id="run_same")
    second, _, _, _ = play(script.select(["B01"]), packs, tmp_path, run_id="run_same")
    assert first.run_dir != second.run_dir and second.run_dir.name == "run_same__2"
    assert read_events(second.run_dir)[0]["run_id"] == "run_same"
    assert os.path.getsize(first.run_dir / "events.jsonl") > 0
