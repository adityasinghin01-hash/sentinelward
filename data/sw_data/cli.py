"""Command line: ``python -m sw_data check | pick-mimic | build | verify``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from sw_data import LOADER_VERSION, EndianError


def _check_one(path: Path, args: argparse.Namespace) -> list[str]:
    import wfdb

    from sw_data import cinc2015, mimic
    from sw_data.dsp import clean_missing, stats_table

    if path.suffix == ".vital":
        from sw_data import vital
        return vital.check_lines(path, start_min=args.start_min, minutes=args.minutes,
                                 clinical=Path(args.clinical) if args.clinical else None)
    if path.is_dir():
        masters = mimic.master_stems(path)
        if not masters:
            raise FileNotFoundError(f"{path}: no MIMIC master records in this folder")
        lines: list[str] = []
        for m in masters:
            lines += mimic.check_master(m)
        return lines
    stem = path.with_suffix("") if path.suffix in (".hea", ".dat") else path
    if not mimic.hea(stem).is_file():
        raise FileNotFoundError(f"{mimic.hea(stem)} not found")
    hdr = wfdb.rdheader(str(stem))
    if getattr(hdr, "seg_name", None):
        return mimic.check_master(stem)
    if mimic.PIECE_RE.match(stem.name):
        return mimic.check_piece(stem)
    if cinc2015.is_cinc_record(hdr):
        return cinc2015.check_lines(stem)
    rec = wfdb.rdrecord(str(stem))
    fs = float(rec.fs)
    return ([f"== {stem.name}  [WFDB record]  {stem}",
             f"  length {rec.sig_len / fs:.1f} s ({rec.sig_len} samples at {fs:g} Hz)"]
            + stats_table([(n, fs, u, clean_missing(rec.p_signal[:, i]))
                           for i, (n, u) in enumerate(zip(rec.sig_name, rec.units))]))


def cmd_check(args: argparse.Namespace) -> int:
    """Print a one-screen report per record or case."""
    rc = 0
    for p in args.paths:
        path = Path(p)
        try:
            lines = _check_one(path, args)
        except EndianError as exc:
            lines, rc = [f"== {path.name}", f"  ERROR: {exc}"], 1
        except Exception as exc:
            lines, rc = [f"== {path.name}", f"  ERROR: {type(exc).__name__}: {exc}"], 1
        print("\n".join(lines))
        print()
    return rc


def cmd_pick_mimic(args: argparse.Namespace) -> int:
    """List the next MIMIC patients with a long II + PLETH piece, with suggested start offsets."""
    from sw_data.mimic import pick_mimic

    exclude = [e for e in (args.exclude or "").split(",") if e.strip()]
    rows = pick_mimic(args.sample_root, exclude, args.need, minutes=args.minutes, min_hours=args.min_hours)
    print(f"{'#':<3}{'patient':<10}{'piece':<16}{'length':>9}  {'suggested start':<22}master")
    for i, r in enumerate(rows, 1):
        print(f"{i:<3}{r['patient']:<10}{r['piece']:<16}{r['length_s'] / 3600:>7.2f} h  "
              f"{r['start_s']:>6.0f} s ({r['start_s'] / 60:>5.1f} min)   {r['master']}")
    for bed, r in zip(("B06", "B11", "B12"), rows):
        print(f"  beds.yaml {bed}: patient: {r['patient']}  piece: \"{r['piece']}\"  start_s: {r['start_s']:.0f}")
    if len(rows) < args.need:
        print(f"only {len(rows)} of {args.need} patients meet the rule (piece >= {args.min_hours:g} h with II and "
              f"PLETH, numerics, a valid {args.minutes}-min window). Suggest VitalDB line cases "
              "(aline1 set) for the remaining beds instead.")
        return 1
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Build bed packs from beds.yaml."""
    from sw_data.build import build

    only = args.beds.split(",") if args.beds else None
    try:
        results = build(args.beds_yaml, args.out, only=only)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    failed = [r for r in results if not r.ok]
    print(f"{len(results) - len(failed)} built, {len(failed)} failed")
    return 1 if failed else 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Reload and re-check every pack in a folder."""
    from sw_data.pack import verify_folder

    out = Path(args.folder)
    if not out.is_dir():
        print(f"ERROR: {out} is not a folder", file=sys.stderr)
        return 2
    results = verify_folder(out)
    if not results:
        print(f"no packs in {out}")
        return 1
    rc = 0
    for bed, problems in results:
        if problems:
            rc = 1
            print(f"{bed} FAIL: {'; '.join(problems)}")
        else:
            print(f"{bed} PASS")
    return rc


def make_parser() -> argparse.ArgumentParser:
    """The argparse parser with the four sub-commands."""
    p = argparse.ArgumentParser(prog="python -m sw_data", description="SentinelWard bed-pack tool")
    p.add_argument("--version", action="version", version=f"sw_data {LOADER_VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="one-screen report per record or case")
    c.add_argument("paths", nargs="+", help="2015 record, MIMIC piece/master/patient folder, or .vital file")
    c.add_argument("--start-min", type=float, default=None, help="VitalDB window start (minute); default: suggested")
    c.add_argument("--minutes", type=int, default=22, help="window length in minutes (default 22)")
    c.add_argument("--clinical", default=None, help="VitalDB clinical_data.csv (aline1 check)")
    c.set_defaults(func=cmd_check)

    m = sub.add_parser("pick-mimic", help="list the next MIMIC patients meeting the bed rule")
    m.add_argument("sample_root")
    m.add_argument("--exclude", default="p000052,p000107,p000109")
    m.add_argument("--need", type=int, default=3)
    m.add_argument("--minutes", type=int, default=22)
    m.add_argument("--min-hours", type=float, default=1.0)
    m.set_defaults(func=cmd_pick_mimic)

    b = sub.add_parser("build", help="write one bed pack per bed plus summary.md")
    b.add_argument("beds_yaml")
    b.add_argument("--out", required=True)
    b.add_argument("--beds", default=None, help="comma-separated subset, e.g. B08,B09,B10")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("verify", help="re-check every pack in a folder")
    v.add_argument("folder")
    v.set_defaults(func=cmd_verify)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the command line; returns the exit code."""
    args = make_parser().parse_args(argv)
    return int(args.func(args))
