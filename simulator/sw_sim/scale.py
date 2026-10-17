"""scale mode (resource test T10): N quiet beds B13.. on top of the ward's ID range.

Each extra bed replays a copy of one of the ward's MIMIC packs, starting at a different pack
second, with its own device ID (MON-13 ...). Alarms are left out so the beds stay quiet.
"""

from __future__ import annotations

import json
import resource
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Mapping

from .clock import Clock
from .config import BedEntry, ScriptError, WardScript
from .engine import Publisher, RunResult, WardRun
from .packs import BedPack

FIRST_SCALE_BED = 13
LAST_BED = 99             # two-digit IDs only (sw_common contract)
MAX_SCALE_BEDS = 87       # B13 .. B99 with the default first bed
OFFSET_STEP_S = 61        # pack-second step between copies of the same pack
MIMIC_SOURCE = "mimic"


def scale_templates(script: WardScript) -> list[str]:
    """Pack names of the ward's MIMIC beds, in script order."""
    names = [b.pack_name for b in script.beds if b.source.lower() == MIMIC_SOURCE]
    if not names:
        raise ScriptError("scale needs at least one bed with source: mimic in the ward script")
    return names


def build_scale_script(script: WardScript, packs: Mapping[str, BedPack], n_beds: int, seconds: int,
                       first_bed: int = FIRST_SCALE_BED) -> WardScript:
    """A script of n_beds quiet copies (B<first_bed>.., MON-<first_bed>..) all joining at T+00:00, lasting `seconds`.

    first_bed defaults to 13 (on top of the ward). first_bed=1 replaces the ward's IDs, for a
    beds-per-brain test with the ward simulator stopped.
    """
    if not 1 <= first_bed <= LAST_BED:
        raise ValueError(f"--first-bed must be 1..{LAST_BED}, got {first_bed}")
    max_beds = LAST_BED - first_bed + 1
    if not 1 <= n_beds <= max_beds:
        raise ValueError(f"--beds must be 1..{max_beds} (IDs B{first_bed:02d}-B{LAST_BED}), got {n_beds}")
    if seconds < 1:
        raise ValueError(f"--seconds must be >= 1, got {seconds}")
    templates = scale_templates(script)
    beds: list[BedEntry] = []
    for i in range(n_beds):
        number = first_bed + i
        name = templates[i % len(templates)]
        room = max(1, packs[name].n_seconds - seconds)
        beds.append(BedEntry(
            bed_id=f"B{number:02d}", device_id=f"MON-{number:02d}", join_s=0,
            pack_start_s=((i // len(templates)) * OFFSET_STEP_S) % room, pack=name,
            source=MIMIC_SOURCE, suppress_alarms=True, note=f"scale copy of {name}",
        ))
    return replace(script, run_length_s=seconds, beds=tuple(beds), drift=None)


@dataclass(frozen=True)
class ScaleReport:
    """Result of a scale run."""

    run_id: str
    run_dir: str
    beds: int
    seconds: int
    status: str
    messages_expected: int
    messages_sent: int
    messages_on_time: int
    on_time_fraction: float
    on_time_per_s_mean: float
    on_time_per_s_min: int
    lag_budget_ms: float
    lag_p50_ms: float | None
    lag_p99_ms: float | None
    lag_max_ms: float | None
    cpu_s: float
    cpu_percent_of_one_core: float
    max_rss_mb: float

    def lines(self) -> list[str]:
        """Human-readable summary."""
        return [
            f"scale run {self.run_id} ({self.status}): {self.beds} beds x {self.seconds} s",
            f"  sent {self.messages_sent}/{self.messages_expected} messages; "
            f"{self.messages_on_time} on time (<= {self.lag_budget_ms:g} ms) = {self.on_time_fraction:.2%}",
            f"  on-time messages per second: mean {self.on_time_per_s_mean:.1f}, min {self.on_time_per_s_min} "
            f"(offered {self.beds}/s)",
            f"  send lag ms: p50 {self.lag_p50_ms}, p99 {self.lag_p99_ms}, max {self.lag_max_ms}",
            f"  CPU {self.cpu_s:.2f} s ({self.cpu_percent_of_one_core:.1f}% of one core), max RSS {self.max_rss_mb:.1f} MB",
            f"  report: {self.run_dir}/report.json",
        ]


def run_scale(script: WardScript, packs: Mapping[str, BedPack], *, n_beds: int, seconds: int, run_id: str,
              runs_dir: str | Path, clock: Clock, bus: Publisher,
              on_run: Callable[[WardRun], None] | None = None, first_bed: int = FIRST_SCALE_BED) -> ScaleReport:
    """Play the scale script and measure on-time sending. on_run(run) is called before it starts."""
    scale_script = build_scale_script(script, packs, n_beds, seconds, first_bed)
    run = WardRun(scale_script, packs, run_id=run_id, runs_dir=runs_dir, clock=clock, bus=bus)
    if on_run is not None:
        on_run(run)
    usage0 = resource.getrusage(resource.RUSAGE_SELF)
    wall0 = time.monotonic()
    result: RunResult = run.run()
    wall = max(time.monotonic() - wall0, 1e-9)
    usage1 = resource.getrusage(resource.RUSAGE_SELF)
    cpu = (usage1.ru_utime - usage0.ru_utime) + (usage1.ru_stime - usage0.ru_stime)

    on_time_counts = [t.on_time for t in result.ticks]
    on_time = sum(on_time_counts)
    report = ScaleReport(
        run_id=run_id, run_dir=str(result.run_dir), beds=n_beds, seconds=seconds, status=result.status,
        messages_expected=n_beds * seconds, messages_sent=result.sent, messages_on_time=on_time,
        on_time_fraction=on_time / (n_beds * seconds),
        on_time_per_s_mean=on_time / len(on_time_counts) if on_time_counts else 0.0,
        on_time_per_s_min=min(on_time_counts) if on_time_counts else 0,
        lag_budget_ms=scale_script.lag_budget_ms, lag_p50_ms=result.lag_p50_ms, lag_p99_ms=result.lag_p99_ms,
        lag_max_ms=result.lag_max_ms, cpu_s=round(cpu, 3), cpu_percent_of_one_core=round(100.0 * cpu / wall, 1),
        max_rss_mb=round(usage1.ru_maxrss / 1024.0, 1),  # Linux reports KiB
    )
    report_path = Path(result.run_dir) / "report.json"
    tmp = report_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    tmp.replace(report_path)
    return report
