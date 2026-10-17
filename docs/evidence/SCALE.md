# Beds per brain on IBM LinuxONE (container stack, one brain container)

Source: raw/evidence/scale-<N>-{ticks,stats,sim}.txt (tick_stats from the brain itself, SW_BRAIN_TICK_STATS=1; docker stats every 30 s). Each run 3 min, simulator scale mode with real MIMIC/2015 packs, 1 vitals message per bed per second, brain ticks every 5 s.

| Beds | Ticks | Verdicts per tick | Tick p50 ms | Tick p99 / max ms | Fits the 5 s tick? | Dropped / invalid | Brain CPU % (peak sample) | Brain RSS MiB (end) |
|---|---|---|---|---|---|---|---|---|
| 12 | 38 | 12 | 79.5 | 111.6 / 111.6 | yes (2.2% of 5 s) | 0 / 0 | 1.02 | 107MiB |
| 24 | 37 | 24 | 160.5 | 229.3 / 229.3 | yes (4.6% of 5 s) | 0 / 0 | 10.23 | 161MiB |
| 48 | 38 | 48 | 311.1 | 376.5 / 376.5 | yes (7.5% of 5 s) | 0 / 0 | 26.96 | 271.6MiB |
| 96 | 37 | 96 | 640.4 | 1121.7 / 1121.7 | yes (22.4% of 5 s) | 0 / 0 | 8.11 | 490.3MiB |

Notes (honest limits):
- The brain container is limited to 1.0 CPU (deploy/containers/compose.yaml); the LinuxONE guest has 3 vCPUs. At 96 beds the slowest tick took 1.12 s of its 5 s budget, so one brain keeps up with 96 beds with about 4x headroom; 96 was the largest bed count tested (B01-B96), the breaking point was not reached.
- Each run lasted 3 minutes, so the 96-bed RSS (490 MiB of a 768 MiB limit) is not yet at its plateau; per-bed history is now bounded (300 s look-back + 30 s), and the 30-minute 12-bed soak plateaued at ~292 MiB (memory-flat.txt). A 96-bed soak was not run.
- CPU % is docker stats sampled every 30 s (peak sample shown), not a continuous average.
