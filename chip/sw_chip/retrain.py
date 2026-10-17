"""Retrain the stretch 1D-CNN exactly as ml_v2/stretch/cnn_nnpa.py did and save its weights.

The original run did not save the weights. This wrapper runs the unchanged
cnn_nnpa.main (same data, seed, mask, early stopping) and captures the best
state_dict at the moment main() loads it, then writes:

    <out_dir>/cnn_state.pt         torch state_dict (CPU tensors)
    <out_dir>/cnn_meta.json        thresholds, held-out numbers, SHA-256 of cnn_state.pt

    python -m sw_chip.retrain <cnn_nnpa.py> windows.npz heldout_mask.npy <out_dir>
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys


def load_script(path):
    spec = importlib.util.spec_from_file_location('cnn_nnpa', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(script, windows, mask, out_dir):
    import torch
    os.makedirs(out_dir, exist_ok=True)
    mod = load_script(script)
    captured = {}
    base = mod.Net

    class CapturingNet(base):
        def load_state_dict(self, sd, *a, **k):
            captured.setdefault('sd', {n: t.detach().clone().cpu() for n, t in sd.items()})
            return super().load_state_dict(sd, *a, **k)

    mod.Net = CapturingNet
    res_path = os.path.join(out_dir, 'cnn_result_retrain.json')
    mod.main(windows, mask, res_path)
    state_path = os.path.join(out_dir, 'cnn_state.pt')
    torch.save(captured['sd'], state_path)
    sha = hashlib.sha256(open(state_path, 'rb').read()).hexdigest()
    res = json.load(open(res_path))
    meta = {
        'model': 'M2-cnn-nnpa-2026-10-17',
        'state_sha256': sha,
        'thresholds': res['thresholds'],
        'best_epoch': res['best_epoch'],
        'heldout_challenge_cinc': res['heldout']['cinc2015/ALL']['score'],
        'heldout_challenge_vtac': res['heldout']['vtac/ALL']['score'],
        'heldout_auroc_cinc': res['heldout']['cinc2015/ALL']['AUROC'],
        'heldout_auroc_vtac': res['heldout']['vtac/ALL']['AUROC'],
        'nnpa': res['nnpa'],
        'torch': torch.__version__,
    }
    json.dump(meta, open(os.path.join(out_dir, 'cnn_meta.json'), 'w'), indent=1)
    print(json.dumps(meta))


if __name__ == '__main__':
    main(*sys.argv[1:5])
