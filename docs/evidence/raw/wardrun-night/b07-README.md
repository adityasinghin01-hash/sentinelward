# B07 counter recomputation

Run `python3 b07_blank_check.py` here using bundled B07-only extracts of every successful ward poll in T+0..1200 s (timestamps, status and B07 bed objects retained). For full originals, use `python3 b07_blank_check.py --source-root /path/to/.work`. Full source files are not bundled; `b07-source-SHA256SUMS` records their hashes, plus the original counter and T0 loader (copied unchanged as `.txt`). `b07-SHA256SUMS` checks the bundled inputs with `shasum -a 256 -c b07-SHA256SUMS`.

The legacy counter labels empty displays at time >100 s as “blank-after-data” without testing previous receipt. B07 deliberately joins at 540 s (`simulator/ward_script.yaml`). All 88 legacy counts per run precede first values; 0 empty-value samples occur after first data in N/F1/F2/F3. Zeros are valid values. This establishes sampled API continuity only; rendered-screen continuity was not measured. Original metrics are preserved as historical outputs.
