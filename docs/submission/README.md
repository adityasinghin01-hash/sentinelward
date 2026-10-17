# Submission assets

By Antara Gupta (17 Oct 2026). Primary versions used for the submission: judge guide = `JUDGE-GUIDE.md` (this folder); architecture = `docs/flowchart/` (larger, more readable render) with this folder's flowchart kept as an alternative; video narration and timings = `docs/VIDEO-SCRIPT.md` (real ward-run times), with this folder's shot list as an alternative caption set.

- `flowchart.mmd` — editable architecture source; rendered as `flowchart.svg` and `flowchart.png`.
- `JUDGE-GUIDE.md` — one-page map from each judging criterion to repository or screen evidence.
- `VIDEO-SHOTLIST.md` — planned 2:50 recording sequence and spoken script.

Re-render the flowchart from the repository root:

```sh
npx -y @mermaid-js/mermaid-cli -i docs/submission/flowchart.mmd -o docs/submission/flowchart.svg --size 1920 -b white
npx -y @mermaid-js/mermaid-cli -i docs/submission/flowchart.mmd -o docs/submission/flowchart.png --size 1920 -b white
```
