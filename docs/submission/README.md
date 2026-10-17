# Submission assets

- `flowchart.mmd` — editable architecture source; rendered as `flowchart.svg` and `flowchart.png`.
- `JUDGE-GUIDE.md` — one-page map from each judging criterion to repository or screen evidence.
- `VIDEO-SHOTLIST.md` — exact 2:50 recording plan and spoken script.

Re-render the flowchart from the repository root:

```sh
npx -y @mermaid-js/mermaid-cli -i docs/submission/flowchart.mmd -o docs/submission/flowchart.svg --size 1920 -b white
npx -y @mermaid-js/mermaid-cli -i docs/submission/flowchart.mmd -o docs/submission/flowchart.png --size 1920 -b white
```
