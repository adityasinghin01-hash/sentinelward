# Beds per brain on IBM LinuxONE (container stack, one brain container)

The unchanged 12/24/48/96-bed originals are bundled in [raw/scale/](raw/scale/README.md), with [SHA-256 hashes](raw/scale/SHA256SUMS). Recompute with `python3 docs/evidence/raw/scale/scale_check.py`; [output](raw/scale/scale_check.txt). These are short, approximately three-minute runs, not a sustained capacity test. They predate container service authentication and do not include agents or the network witness.

Only tick records where both `beds` and `verdicts` match the tested count are included (startup ticks excluded). Drops/invalid are the maximum recorded cumulative counters in those matching ticks.

| Beds / verdicts per tick | Matching ticks | Median tick ms | Maximum tick ms | Recorded drops / invalid |
|---|---|---|---|---|
| 12 | 38 | 79.54 | 111.64 | 0 / 0 |
| 24 | 37 | 160.51 | 229.35 | 0 / 0 |
| 48 | 38 | 311.15 | 376.53 | 0 / 0 |
| 96 | 37 | 640.44 | 1121.65 | 0 / 0 |

All recorded matching ticks finished within the 5-second tick period; the 96-bed maximum was 22.4% of that period. The brain container was limited to 1.0 CPU on a 3-vCPU guest. This does not establish a capacity ceiling or a measured throughput margin. No 96-bed soak was run. The stats files are sampled resource observations, not continuous CPU averages or proof of a memory plateau. The separate 30-minute **12-bed** soak plateaued near 292 MiB (`raw/memory-flat.txt`); it does not establish 96-bed memory stability.

**Older rejected-extra-bed run:** `raw/containers/scale-stats.txt` and `raw/containers/scale-report.json` describe `scale_20261017_121343`: 87 extra beds B13–B99 for 60 s alongside the 12-bed ward, 5,220 messages and 5,220 “Expected ward bed” rejections. That is publication, not extra-bed inference. The later logs above are a separate cohort using the extended acceptance range: `brain/sw_brain/io.py` supports `SW_BRAIN_MAX_BED` (default 12, allowed 1–99); `brain/tests/test_scale.py` checks that boundary.

**Separate AI-chip benchmark:** `chip/results/batch_bench.json` (repo root) records 12 batches of 96 CNN windows on the TEST guest, 2 threads: nnpa:0 median/max 89.1/124.6 ms, CPU 89.6/151.0 ms. This scores CNN windows only, with no hub or full brain pipeline, and demonstrates no NNPA speed advantage.
