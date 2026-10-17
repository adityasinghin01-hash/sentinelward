# Beds per brain on IBM LinuxONE (container stack, one brain container)

**Evidence limit:** the later 12/24/48/96-bed figures below are a recorded summary. Their cited `raw/evidence/scale-<N>-{ticks,stats,sim}.txt` **logs are not bundled** in this repository; these rows cannot be independently recomputed from the supplied pack. The summary describes 3-minute runs, real MIMIC/2015 packs, 1 vitals message per bed per second, brain ticks every 5 s, `SW_BRAIN_TICK_STATS=1` and docker stats every 30 s. The separate AI-chip row is backed by checked-in `chip/results/batch_bench.json`.

**Older bundled run:** `raw/containers/scale-stats.txt` and `raw/containers/scale-report.json` describe `scale_20261017_121343`: 87 extra beds B13–B99 for 60 s alongside the 12-bed ward. The simulator sent 5,220 messages; the brain logged **5,220 "Expected ward bed" rejections** because its input check accepted only B01–B12. That capture demonstrates extra-bed publication, not extra-bed inference. The current `brain/sw_brain/io.py` adds `SW_BRAIN_MAX_BED` (default 12, allowed 1–99), used by `set_max_bed` to extend both accepted bed and device sets; `brain/tests/test_scale.py` exercises this boundary. Set it to 96 for B01–B96. This code change explains how later acceptance is possible; it does not recover or verify the absent later tick logs.

| Beds | Ticks | Verdicts per tick | Tick p50 ms | Tick p99 / max ms | Fits the 5 s tick? | Dropped / invalid | Brain CPU % (peak sample) | Brain RSS MiB (end) |
|---|---|---|---|---|---|---|---|---|
| 12 | 38 | 12 | 79.5 | 111.6 / 111.6 | yes (2.2% of 5 s) | 0 / 0 | 1.02 | 107MiB |
| 24 | 37 | 24 | 160.5 | 229.3 / 229.3 | yes (4.6% of 5 s) | 0 / 0 | 10.23 | 161MiB |
| 48 | 38 | 48 | 311.1 | 376.5 / 376.5 | yes (7.5% of 5 s) | 0 / 0 | 26.96 | 271.6MiB |
| 96 | 37 | 96 | 640.4 | 1121.7 / 1121.7 | yes (22.4% of 5 s) | 0 / 0 | 8.11 | 490.3MiB |
| 96, AI-chip CNN only (TEST guest, 2 vCPU, all 96 windows in one batch per tick, 2 threads; `chip/results/batch_bench.json`) | 12 | 96 CNN scores (shown only) | nnpa:0 89.1 · cpu 89.6 | nnpa:0 124.6 · cpu 151.0 (max of 12) | yes (≤3.1% of 5 s) | n/a (bench, no hub) | nnpa:0 1.29 · cpu 1.21 (% of guest) | not measured |

Notes (honest limits):
- In the reported later runs, the brain container is limited to 1.0 CPU (deploy/containers/compose.yaml); the LinuxONE guest has 3 vCPUs. At 96 beds the slowest tick took 1.12 s of its 5 s budget, in that short summary; this is not a demonstrated capacity ceiling or a measured 4× throughput margin. 96 was the largest reported bed count (B01–B96); the breaking point was not measured.
- Each reported later run lasted 3 minutes, so the 96-bed RSS (490 MiB of a 768 MiB limit) does not establish a plateau; per-bed history is now bounded (300 s look-back + 30 s), and the 30-minute 12-bed soak plateaued at ~292 MiB (`raw/memory-flat.txt`). A 96-bed soak was not run.
- CPU % is docker stats sampled every 30 s (peak sample shown), not a continuous average.
