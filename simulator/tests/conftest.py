"""Shared test fixtures: synthetic bed packs, a fake bus, a fake clock. No broker needed."""

from __future__ import annotations

import json
import random
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sw_common  # noqa: E402  (the real shared package)

from sw_sim.config import load_script  # noqa: E402
from sw_sim.engine import RunResult, WardRun  # noqa: E402
from sw_sim.packs import load_packs  # noqa: E402

SCRIPT_PATH = ROOT / "ward_script.yaml"
FS = 125

MIMIC = ("B01", "B02", "B05", "B06", "B11", "B12")
VITALDB = ("B08", "B09", "B10")

# Known features of the synthetic packs, used by the tests.
B01_NAN_ECG = (50, 7)                # pack second 50, sample 7 is NaN
B01_CUFF = [(120.7, 131.0, 84.0, 99.0)]
B02_HR_ZERO_S = 20
B02_HR_NAN_S = 10
B08_CUFF = [(0.0, 120.0, 80.0, 93.0), (300.4, 118.0, 78.0, 91.0), (600.0, 121.0, 79.0, 93.0), (1100.25, 119.0, 77.0, 91.0)]
ALARMS = {
    "B03": {"t_offset_s": 300.0, "code": "VTACH", "true_alarm": True, "priority": "high"},
    "B04": {"t_offset_s": 300.0, "code": "ASYSTOLE", "true_alarm": False, "priority": "high"},
    "B07": {"t_offset_s": 300.0, "code": "VFIB", "true_alarm": True, "priority": "high"},
}


def write_pack(folder: Path, bed_id: str, duration_s: int, *, abp: bool = True,
               cuff: list[tuple[float, float, float, float]] | None = None,
               alarms: list[dict] | None = None, seed: int = 0) -> None:
    """Write <bed_id>.npz (float32 little-endian) and <bed_id>.json like the data loader does."""
    n = duration_s * FS
    i = np.arange(n, dtype=np.float64)
    phase = seed * 0.37
    arrays: dict[str, np.ndarray] = {
        "ecg": np.sin(2 * np.pi * i / FS + phase) * 1.2,
        "ppg": 50.0 + 10.0 * np.sin(2 * np.pi * i / 110.0 + phase),
    }
    if abp:
        arrays["abp"] = 90.0 + 20.0 * np.sin(2 * np.pi * i / 100.0 + phase)
    s = np.arange(duration_s, dtype=np.float64)
    arrays["hr"] = 70.0 + (s % 10)
    arrays["spo2"] = np.full(duration_s, 97.0)
    arrays["rr"] = 14.0 + (s % 4)
    if bed_id == "B01" and duration_s > B01_NAN_ECG[0]:
        sec, smp = B01_NAN_ECG
        arrays["ecg"][sec * FS + smp] = np.nan
    if bed_id == "B02" and duration_s > B02_HR_ZERO_S:
        arrays["hr"][B02_HR_ZERO_S] = 0.0
        arrays["hr"][B02_HR_NAN_S] = np.nan
    out = {k: v.astype("<f4") for k, v in arrays.items()}
    out["nibp"] = np.asarray(cuff or [], dtype="<f4").reshape(-1, 4)
    np.savez(folder / f"{bed_id}.npz", **out)
    meta = {
        "bed_id": bed_id, "device_id": f"MON-{bed_id[1:]}", "fs": FS, "duration_s": duration_s,
        "channels": [c for c in ("ecg", "ppg", "abp", "hr", "spo2", "rr", "nibp") if c in out and out[c].size],
        "alarms": alarms or [],
    }
    (folder / f"{bed_id}.json").write_text(json.dumps(meta), encoding="utf-8")


@pytest.fixture(scope="session")
def packs_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The 12 synthetic ward packs."""
    folder = tmp_path_factory.mktemp("packs")
    for n, bed in enumerate(MIMIC):
        write_pack(folder, bed, 1210 if bed == "B12" else 1200, seed=n,
                   cuff=B01_CUFF if bed == "B01" else None)
    for n, bed in enumerate(VITALDB):
        write_pack(folder, bed, 1200, seed=10 + n, cuff=B08_CUFF if bed == "B08" else None)
    write_pack(folder, "B03", 330, seed=20, alarms=[ALARMS["B03"]])
    write_pack(folder, "B04", 330, seed=21, abp=False, alarms=[ALARMS["B04"]])
    write_pack(folder, "B07", 330, seed=22, alarms=[ALARMS["B07"]])
    return folder


@pytest.fixture(scope="session")
def script():
    """The real ward_script.yaml."""
    return load_script(SCRIPT_PATH)


@pytest.fixture(scope="session")
def packs(packs_dir, script):
    """All ward packs, loaded."""
    return load_packs(packs_dir, [b.pack_name for b in script.beds])


class FakeBus:
    """Records published messages; validates each one; lets tests inject control messages.

    fail_for(message) -> True makes publish raise; drop_for(message) -> True makes it return False,
    like sw_common.Bus dropping a QoS 0 message while disconnected.
    """

    def __init__(self, fail_for: Callable[[dict], bool] | None = None,
                 drop_for: Callable[[dict], bool] | None = None) -> None:
        self.messages: list[dict] = []
        self.validation_errors: list[tuple[dict, list[str]]] = []
        self.handlers: list[tuple[str, Callable[[Any, str], None]]] = []
        self.closed = False
        self._fail_for = fail_for
        self._drop_for = drop_for
        self._lock = threading.Lock()

    def connect(self) -> None:
        pass

    def publish(self, message: dict) -> bool:
        if self._fail_for is not None and self._fail_for(message):
            raise ConnectionError("fake publish failure")
        if self._drop_for is not None and self._drop_for(message):
            return False
        errors = sw_common.validate(message)
        with self._lock:
            if errors:
                self.validation_errors.append((message, list(errors)))
            self.messages.append(message)
        return True

    def subscribe(self, pattern: str, handler: Callable[[Any, str], None]) -> None:
        self.handlers.append((pattern, handler))

    def inject(self, topic: str, message: Any) -> None:
        for pattern, handler in self.handlers:
            if pattern == topic:
                handler(message, topic)

    def close(self) -> None:
        self.closed = True

    def by_bed(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for m in self.messages:
            out.setdefault(m["bed_id"], []).append(m)
        return out


class FakeClock:
    """Jumps to each wait target, optionally with +/- jitter; records every target it was given."""

    speed = 1.0
    fast = False

    def __init__(self, start_ms: float | None = None, jitter_ms: float = 0.0, seed: int = 0) -> None:
        self._now = float(int(time.time()) * 1000 if start_ms is None else start_ms)
        self._jitter = jitter_ms
        self._rng = random.Random(seed)
        self.targets: list[float] = []

    def now_ms(self) -> float:
        return self._now

    def wait_until(self, target_ms: float, stop: threading.Event) -> bool:
        if stop.is_set():
            return True
        self.targets.append(target_ms)
        jitter = self._rng.uniform(-self._jitter, self._jitter) if self._jitter else 0.0
        self._now = float(target_ms) + jitter
        return False


def read_events(run_dir: Path) -> list[dict]:
    """All lines of events.jsonl."""
    return [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def play(script, packs, tmp_path: Path, *, start_at_s: int = 0, clock: FakeClock | None = None,
         bus: FakeBus | None = None, run_id: str = "run_test") -> tuple[RunResult, FakeBus, list[dict], FakeClock]:
    """Run a whole script on the fake clock and fake bus."""
    clock = clock or FakeClock()
    bus = bus or FakeBus()
    run = WardRun(script, packs, run_id=run_id, runs_dir=tmp_path / "runs", clock=clock, bus=bus,
                  start_at_s=start_at_s)
    result = run.run()
    return result, bus, read_events(result.run_dir), clock


@pytest.fixture(scope="session")
def full_run(script, packs, tmp_path_factory):
    """One full 20-minute run on the fake clock, shared by many tests."""
    return play(script, packs, tmp_path_factory.mktemp("full"))
