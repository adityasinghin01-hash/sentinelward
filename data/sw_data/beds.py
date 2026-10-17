"""beds.yaml loading and validation, plus the data model passed from source readers to the builder."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import yaml

from sw_data import BedError

DATASETS = ("cinc2015", "mimic", "vitaldb")
WAVE_SIGNALS = ("ecg", "ppg", "abp", "resp")
ALLOWED_SIGNALS = {
    "cinc2015": {"ecg", "ppg", "abp", "resp"},
    "mimic": {"ecg", "ppg", "abp", "resp", "numerics"},
    "vitaldb": {"ecg", "ppg", "abp", "numbers", "cuff"},
}
H1_HINTS = {
    "mimic": "H1 PICK: run `python -m sw_data pick-mimic <root> --exclude p000052,p000107,p000109 --need 3`",
    "vitaldb": "H1 WINDOW: run `python -m sw_data check <case>.vital` and use its suggested start",
    "cinc2015": "H1 CONFIRM: run `python -m sw_data check <record>`",
}


@dataclass
class Paths:
    """Source data locations from the ``paths:`` block (absolute)."""

    cinc2015: Optional[Path] = None
    mimic: Optional[Path] = None
    vitaldb: Optional[Path] = None
    vitaldb_clinical: Optional[Path] = None


@dataclass
class BedSpec:
    """One bed from beds.yaml."""

    bed_id: str
    device_id: str
    dataset: str
    signals: list[str]
    duration_s: Optional[int] = None
    record: Optional[str] = None
    backup_record: Optional[str] = None
    patient: Optional[str] = None
    piece: Optional[str] = None
    start_s: Optional[float] = None
    case: Optional[int] = None
    backup_case: Optional[int] = None
    start_min: Optional[float] = None
    window_ref: str = "file"

    def require(self, *names: str) -> None:
        """Raise BedError if any of the named fields is still unset (an H1 field not filled in)."""
        empty = [n for n in names if getattr(self, n) is None]
        if empty:
            raise BedError(self.bed_id, f"{', '.join(empty)} not filled in; {H1_HINTS[self.dataset]}")

    def wants(self, signal: str) -> bool:
        """True if ``signal`` is required for this bed."""
        return signal in self.signals


@dataclass
class SourceData:
    """Everything a source reader extracts for one bed window, already on the pack grids."""

    dataset: str
    duration_s: int
    source: dict[str, Any]
    waves: dict[str, np.ndarray] = field(default_factory=dict)      # 125 Hz, NaN = missing
    hr: Optional[np.ndarray] = None                                  # 1 Hz
    spo2: Optional[np.ndarray] = None
    rr: Optional[np.ndarray] = None
    nibp: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))
    alarms: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    numerics_found: bool = False
    cuff_found: bool = False


def _resolve(base: Path, value: Any) -> Optional[Path]:
    if value in (None, ""):
        return None
    p = Path(str(value)).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def _opt_int(bed_id: str, key: str, value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{bed_id}: {key} must be an integer, got {value!r}") from None


def _opt_float(bed_id: str, key: str, value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{bed_id}: {key} must be a number, got {value!r}") from None


def parse_bed(raw: dict[str, Any]) -> BedSpec:
    """Validate one bed mapping and return a BedSpec (H1 fields may still be null)."""
    bed_id = str(raw.get("bed_id", "")).strip()
    if not re.fullmatch(r"B\d{2}", bed_id):
        raise ValueError(f"bed_id must look like B01, got {bed_id!r}")
    dataset = raw.get("dataset")
    if dataset not in DATASETS:
        raise ValueError(f"{bed_id}: dataset must be one of {DATASETS}, got {dataset!r}")
    device_id = str(raw.get("device_id") or f"MON-{bed_id[1:]}")
    signals = [str(s).lower() for s in (raw.get("signals") or [])]
    bad = [s for s in signals if s not in ALLOWED_SIGNALS[dataset]]
    if bad:
        raise ValueError(f"{bed_id}: signals {bad} not valid for {dataset} "
                         f"(allowed: {sorted(ALLOWED_SIGNALS[dataset])})")
    spec = BedSpec(
        bed_id=bed_id,
        device_id=device_id,
        dataset=dataset,
        signals=signals,
        duration_s=_opt_int(bed_id, "duration_s", raw.get("duration_s")),
        record=None if raw.get("record") is None else str(raw["record"]),
        backup_record=None if raw.get("backup_record") is None else str(raw["backup_record"]),
        patient=None if raw.get("patient") is None else str(raw["patient"]),
        piece=None if raw.get("piece") is None else str(raw["piece"]),
        start_s=_opt_float(bed_id, "start_s", raw.get("start_s")),
        case=_opt_int(bed_id, "case", raw.get("case")),
        backup_case=_opt_int(bed_id, "backup_case", raw.get("backup_case")),
        start_min=_opt_float(bed_id, "start_min", raw.get("start_min")),
        window_ref=str(raw.get("window_ref") or "file"),
    )
    if spec.window_ref not in ("file", "opstart"):
        raise ValueError(f"{bed_id}: window_ref must be 'file' or 'opstart', got {spec.window_ref!r}")
    piece = raw.get("piece")
    if piece is not None and (not isinstance(piece, str) or not re.fullmatch(r"\d+_\d{4}", piece)):
        raise ValueError(f"{bed_id}: piece must be a quoted name like '3346682_0014', got {piece!r} "
                         "(YAML reads an unquoted 3346682_0014 as the number 33466820014)")
    if dataset in ("mimic", "vitaldb") and spec.duration_s is not None and spec.duration_s <= 0:
        raise ValueError(f"{bed_id}: duration_s must be positive")
    if spec.start_s is not None and spec.start_s < 0:
        raise ValueError(f"{bed_id}: start_s must not be negative")
    if spec.start_min is not None and spec.start_min < 0:
        raise ValueError(f"{bed_id}: start_min must not be negative")
    return spec


def load_beds(path: str | Path) -> tuple[Paths, list[BedSpec]]:
    """Load beds.yaml; raise ValueError on structural problems or a source used on two beds."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    if not isinstance(doc, dict) or not isinstance(doc.get("beds"), list):
        raise ValueError(f"{path}: expected a mapping with a 'beds' list")
    base = path.resolve().parent
    p = doc.get("paths") or {}
    paths = Paths(
        cinc2015=_resolve(base, p.get("cinc2015")),
        mimic=_resolve(base, p.get("mimic")),
        vitaldb=_resolve(base, p.get("vitaldb")),
        vitaldb_clinical=_resolve(base, p.get("vitaldb_clinical")),
    )
    specs = [parse_bed(b) for b in doc["beds"]]
    seen_ids: set[str] = set()
    seen_dev: set[str] = set()
    seen_src: dict[tuple[str, str], str] = {}
    for s in specs:
        if s.bed_id in seen_ids:
            raise ValueError(f"{s.bed_id}: bed_id appears twice")
        if s.device_id in seen_dev:
            raise ValueError(f"{s.bed_id}: device_id {s.device_id} appears twice")
        seen_ids.add(s.bed_id)
        seen_dev.add(s.device_id)
        key_val = {"cinc2015": s.record, "mimic": s.patient,
                   "vitaldb": None if s.case is None else str(s.case)}[s.dataset]
        if key_val is not None:
            key = (s.dataset, key_val)
            if key in seen_src:
                raise ValueError(f"{s.bed_id}: {s.dataset} {key_val} is already used by {seen_src[key]} "
                                 "(never use one patient on two beds)")
            seen_src[key] = s.bed_id
    return paths, specs
