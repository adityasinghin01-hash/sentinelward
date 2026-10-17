# Scale originals

Unchanged bytes copied from `.work/evidence-scale/raw/evidence/scale-*.txt` on 18 Oct 2026. `SHA256SUMS` records every source copy (including `scale-nohup.txt`); verify with `shasum -a 256 -c SHA256SUMS` here. Tick, simulator and sampled resource logs cover short runs, not a sustained capacity limit.

Run `python3 scale_check.py` here to reproduce matching tick counts, median/max tick milliseconds and maximum recorded cumulative drop/invalid counters. Only ticks where both `beds` and `verdicts` equal the tested bed count are included; startup ticks are excluded. See [SCALE.md](../../SCALE.md) for scope and the separate older rejected-extra-bed capture.
