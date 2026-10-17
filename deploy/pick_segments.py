"""Pick the longest continuous piece with II + PLETH per MIMIC-III matched patient.

Read-only. Stdlib only. Usage: python3 pick_segments.py SAMPLE_DIR pXXXXXX [...]
A "piece" = consecutive non-gap segments inside one master record, every segment
containing both II and PLETH. A "~" gap segment or a segment missing either signal ends it.
Prints JSON: per patient, the best piece, its duration and the exact files to copy.
"""
import json
import os
import sys

FS_DEFAULT = 125


def read_header(path):
    with open(path) as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


def seg_signals(pdir, seg):
    lines = read_header(os.path.join(pdir, seg + ".hea"))
    return {ln.split()[-1] for ln in lines[1:]}


def best_piece(pdir, master):
    lines = read_header(os.path.join(pdir, master))
    fs = float(lines[0].split()[2].split("/")[0]) if len(lines[0].split()) > 2 else FS_DEFAULT
    best, cur = None, []

    def close():
        nonlocal best, cur
        if cur:
            n = sum(s[1] for s in cur)
            if best is None or n > best["samples"]:
                best = {"master": master, "segments": [s[0] for s in cur], "samples": n, "fs": fs}
        cur = []

    for ln in lines[1:]:
        name, length = ln.split()[0], int(ln.split()[1])
        if name.endswith("_layout"):
            continue
        if name == "~":
            close()
            continue
        sigs = seg_signals(pdir, name)
        if "II" in sigs and "PLETH" in sigs and length > 0:
            cur.append((name, length))
        else:
            close()
    close()
    return best


def numerics_for(pdir, master, segments):
    """Numerics header with the same name + 'n' plus the .dat files it references."""
    rec = segments[0].split("_")[0]
    cands = [master[:-4] + "n.hea"] + [f for f in os.listdir(pdir) if f.endswith("n.hea") and f.startswith(os.path.basename(pdir))]
    for h in cands:
        p = os.path.join(pdir, h)
        if not os.path.exists(p):
            continue
        lines = read_header(p)
        dats = sorted({ln.split()[0] for ln in lines[1:]})
        if any(d.startswith(rec) for d in dats):
            return [h] + dats
    return []


def main():
    root = sys.argv[1]
    out = {}
    for pid in sys.argv[2:]:
        pdir = os.path.join(root, pid[:3], pid)
        masters = sorted(f for f in os.listdir(pdir) if f.startswith(pid) and f.endswith(".hea") and not f.endswith("n.hea"))
        pieces = [b for b in (best_piece(pdir, m) for m in masters) if b]
        if not pieces:
            out[pid] = None
            continue
        b = max(pieces, key=lambda x: x["samples"])
        rec = b["segments"][0].split("_")[0]
        files = [b["master"], rec + "_layout.hea"]
        for s in b["segments"]:
            files += [s + ".hea", s + ".dat"]
        files += numerics_for(pdir, b["master"], b["segments"])
        rel = [os.path.join(pid[:3], pid, f) for f in files]
        size = sum(os.path.getsize(os.path.join(root, r)) for r in rel)
        out[pid] = {
            "master": b["master"], "first": b["segments"][0], "last": b["segments"][-1],
            "n_segments": len(b["segments"]), "hours": round(b["samples"] / b["fs"] / 3600, 2),
            "folder_bytes": sum(os.path.getsize(os.path.join(pdir, f)) for f in os.listdir(pdir)),
            "copy_bytes": size, "files": rel,
        }
    json.dump(out, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
