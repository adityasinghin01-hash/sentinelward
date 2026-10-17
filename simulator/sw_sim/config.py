"""Configuration: environment variables, the ward script file, and T+mm:ss times."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .drift import DriftSpec

WAVE_CHANNELS = ("ecg", "ppg", "abp")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_START_AT_RE = re.compile(r"^(?:T\+)?(?:(\d+):([0-5]\d)|(\d+))$")


class ScriptError(ValueError):
    """The ward script is missing a field or holds an inconsistent value."""


@dataclass(frozen=True)
class Env:
    """Settings taken from environment variables."""

    mqtt_host: str
    mqtt_port: int
    mqtt_user: str | None
    mqtt_pass: str | None
    packs_dir: Path
    runs_dir: Path


def load_env(environ: Mapping[str, str] | None = None) -> Env:
    """Read MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, SW_PACKS and SW_RUNS."""
    env = os.environ if environ is None else environ
    port_text = env.get("MQTT_PORT") or "1883"
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError(f"MQTT_PORT must be an integer, got {port_text!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"MQTT_PORT out of range: {port}")
    return Env(
        mqtt_host=env.get("MQTT_HOST") or "localhost",
        mqtt_port=port,
        mqtt_user=env.get("MQTT_USER") or None,
        mqtt_pass=env.get("MQTT_PASS") or None,
        packs_dir=Path(env.get("SW_PACKS") or "packs"),
        runs_dir=Path(env.get("SW_RUNS") or "runs"),
    )


@dataclass(frozen=True)
class BedEntry:
    """One monitor in the script: when it starts sending and from which pack second."""

    bed_id: str
    join_s: int
    pack_start_s: int = 0
    pack: str = ""                # pack file stem; empty = same as bed_id
    device_id: str | None = None  # None = use the pack's device_id
    source: str = ""
    suppress_alarms: bool = False
    loop_pack: bool = False       # scale mode only: restart the pack at its end (seq/ts keep going)
    note: str = ""

    @property
    def pack_name(self) -> str:
        """File stem of the pack this bed plays."""
        return self.pack or self.bed_id


@dataclass(frozen=True)
class WardScript:
    """The whole ward script as data."""

    run_length_s: int
    fs: int
    beds: tuple[BedEntry, ...]
    drift: DriftSpec | None
    rounding: Mapping[str, int]
    lag_budget_ms: float
    lead_ms: int
    mqtt_client_id: str

    def bed_ids(self) -> list[str]:
        """Bed IDs in script order."""
        return [b.bed_id for b in self.beds]

    def select(self, bed_ids: Sequence[str] | None) -> "WardScript":
        """Return the script restricted to bed_ids (script order kept); None or empty = all."""
        if not bed_ids:
            return self
        wanted = list(dict.fromkeys(bed_ids))
        known = set(self.bed_ids())
        unknown = [b for b in wanted if b not in known]
        if unknown:
            raise ScriptError(f"unknown bed(s) {', '.join(unknown)}; script has {', '.join(self.bed_ids())}")
        beds = tuple(b for b in self.beds if b.bed_id in wanted)
        drift = self.drift if self.drift is not None and self.drift.bed_id in wanted else None
        return replace(self, beds=beds, drift=drift)


def _get_int(data: Mapping[str, Any], key: str, where: str, default: int | None = None, minimum: int = 0) -> int:
    if key not in data:
        if default is None:
            raise ScriptError(f"{where}: missing {key!r}")
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScriptError(f"{where}: {key!r} must be a whole number, got {value!r}")
    if value < minimum:
        raise ScriptError(f"{where}: {key!r} must be >= {minimum}, got {value}")
    return value


def _get_number(data: Mapping[str, Any], key: str, where: str, default: float | None = None) -> float:
    if key not in data:
        if default is None:
            raise ScriptError(f"{where}: missing {key!r}")
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScriptError(f"{where}: {key!r} must be a number, got {value!r}")
    return float(value)


def parse_script(data: Any) -> WardScript:
    """Build and check a WardScript from parsed YAML data."""
    if not isinstance(data, Mapping):
        raise ScriptError("ward script must be a mapping")
    if data.get("version", 1) != 1:
        raise ScriptError(f"unsupported ward script version {data.get('version')!r}")
    run_length = _get_int(data, "run_length_s", "script", minimum=1)
    fs = _get_int(data, "fs", "script", minimum=1)
    lead_ms = _get_int(data, "lead_ms", "script", default=1000)
    lag_budget = _get_number(data, "lag_budget_ms", "script", default=50.0)
    client_id = str(data.get("mqtt_client_id") or "sw_sim")

    rounding_raw = data.get("rounding") or {}
    if not isinstance(rounding_raw, Mapping):
        raise ScriptError("script: 'rounding' must be a mapping")
    rounding = {ch: _get_int(rounding_raw, ch, "rounding", default=d) for ch, d in (("ecg", 3), ("ppg", 2), ("abp", 1))}

    beds_raw = data.get("beds")
    if not isinstance(beds_raw, list) or not beds_raw:
        raise ScriptError("script: 'beds' must be a non-empty list")
    beds: list[BedEntry] = []
    seen: set[str] = set()
    for i, raw in enumerate(beds_raw):
        where = f"beds[{i}]"
        if not isinstance(raw, Mapping) or not isinstance(raw.get("bed_id"), str):
            raise ScriptError(f"{where}: needs a string 'bed_id'")
        bed_id = raw["bed_id"]
        if bed_id in seen:
            raise ScriptError(f"{where}: duplicate bed_id {bed_id}")
        seen.add(bed_id)
        join_s = _get_int(raw, "join_s", f"{where} ({bed_id})")
        if join_s >= run_length:
            raise ScriptError(f"{where} ({bed_id}): join_s {join_s} is not inside the run (0..{run_length - 1})")
        device_id = raw.get("device_id")
        if device_id is not None and not isinstance(device_id, str):
            raise ScriptError(f"{where} ({bed_id}): 'device_id' must be a string")
        beds.append(BedEntry(
            bed_id=bed_id,
            join_s=join_s,
            pack_start_s=_get_int(raw, "pack_start_s", f"{where} ({bed_id})", default=0),
            pack=str(raw.get("pack") or ""),
            device_id=device_id,
            source=str(raw.get("source") or ""),
            suppress_alarms=bool(raw.get("suppress_alarms", False)),
            note=str(raw.get("note") or ""),
        ))

    drift: DriftSpec | None = None
    drift_raw = data.get("drift")
    if drift_raw is not None:
        if not isinstance(drift_raw, Mapping) or not isinstance(drift_raw.get("bed_id"), str):
            raise ScriptError("drift: needs a string 'bed_id'")
        if drift_raw["bed_id"] not in seen:
            raise ScriptError(f"drift: bed {drift_raw['bed_id']} is not in 'beds'")
        try:
            drift = DriftSpec(
                bed_id=drift_raw["bed_id"],
                channel=str(drift_raw.get("channel", "abp")),
                ramp_start_s=_get_int(drift_raw, "ramp_start_s", "drift"),
                ramp_end_s=_get_int(drift_raw, "ramp_end_s", "drift"),
                hold_end_s=_get_int(drift_raw, "hold_end_s", "drift"),
                peak_mmHg=_get_number(drift_raw, "peak_mmHg", "drift"),
            )
        except ValueError as exc:
            raise ScriptError(f"drift: {exc}") from exc

    return WardScript(
        run_length_s=run_length, fs=fs, beds=tuple(beds), drift=drift, rounding=rounding,
        lag_budget_ms=lag_budget, lead_ms=lead_ms, mqtt_client_id=client_id,
    )


def load_script(path: str | Path) -> WardScript:
    """Load and check ward_script.yaml."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScriptError(f"cannot read ward script {path}: {exc}") from exc
    return parse_script(yaml.safe_load(text))


def parse_start_at(text: str) -> int:
    """Parse 'T+mm:ss', 'mm:ss' or plain seconds into whole seconds."""
    m = _START_AT_RE.match(text.strip())
    if not m:
        raise ValueError(f"start time must look like T+mm:ss (e.g. T+04:30), got {text!r}")
    if m.group(3) is not None:
        return int(m.group(3))
    return int(m.group(1)) * 60 + int(m.group(2))


def format_t(t_s: float) -> str:
    """Format seconds as T+mm:ss."""
    whole = int(t_s)
    return f"T+{whole // 60:02d}:{whole % 60:02d}"


def check_run_id(run_id: str) -> str:
    """Return run_id if it is safe to use as a folder name, else raise ValueError."""
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise ValueError(f"run_id must match {RUN_ID_RE.pattern}, got {run_id!r}")
    return run_id
