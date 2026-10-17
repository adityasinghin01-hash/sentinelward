"""Shared fixtures: the contract's example messages, one fresh copy per call."""

from __future__ import annotations

import copy
from typing import Any, Callable

import pytest

ECG = [round(0.01 * (i % 50) - 0.2, 3) for i in range(125)]
PPG = [round(0.5 + 0.004 * i, 3) for i in range(125)]
ABP = [80.0 + (i % 25) for i in range(125)]

EXAMPLES: dict[str, dict[str, Any]] = {
    "vitals": {
        "v": 1, "type": "vitals", "bed_id": "B03", "device_id": "MON-03", "seq": 18452,
        "ts": 1792252800000, "fs": 125, "ecg": ECG, "ppg": PPG, "abp": ABP,
        "hr": 82, "spo2": 97, "rr": 16,
        "nibp": {"sys": 118, "dia": 72, "map": 87, "ts": 1792252790000},
        "monitor_alarm": {"code": "VTACH", "priority": "high"},
    },
    "score": {
        "v": 1, "type": "score", "bed_id": "B03", "model": "M3", "model_version": "m3-2026-10-17a",
        "window_start": 1792252795000, "window_s": 10, "score": 0.91, "label": "body_mismatch",
        "reason": "Pulse arrives 480 ms after the heartbeat; this patient's usual is 205 ms", "extra": {},
    },
    "verdict": {
        "v": 1, "type": "verdict", "bed_id": "B07", "ts": 1792252800500, "window_start": 1792252795000,
        "verdict": "TAMPERING", "priority": "medium", "confidence": 0.88, "trust": 0.12,
        "last_trusted_ts": 1792252620000,
        "reasons": ["Same 10 seconds seen 4 minutes ago (replay)", "Heartbeat and pulse no longer match",
                    "Network sender changed"],
        "scores": {"M1": 0.10, "M2": 0.05, "M3": 0.91, "M4": 0.99, "M5": 0.74, "M6": 0.02},
    },
    "action": {
        "v": 1, "type": "action", "action_id": "act_000231", "ts": 1792252801200, "by": "A2",
        "action": "disable_client", "bed_id": "B07", "device_id": "MON-07",
        "detail": "Cut off MON-07 after TAMPERING (conf 0.88); session wiped", "undo_id": "act_000231",
        "undoes": None, "approved_by": None, "result": "ok",
    },
    "alert": {
        "v": 1, "type": "alert", "alert_id": "al_0042", "ts": 1792252803000, "bed_id": "B03",
        "verdict": "EMERGENCY", "priority": "high", "text": "Bed 3 — possible heart emergency. Go now.",
        "to": ["staff:priya"], "ladder_step": 1, "status": "open", "acked_by": None, "acked_ts": None,
    },
    "bedside_check": {
        "v": 1, "type": "bedside_check", "bed_id": "B07", "ts": 1792252860000, "result": "patient_ok",
        "by": "staff:priya",
    },
    "net_features": {
        "v": 1, "type": "net_features", "device_id": "MON-07", "window_start": 1792252795000, "window_s": 5,
        "msgs_per_s": 1.0, "bytes_per_s": 3100, "iat_mean_ms": 1000, "iat_std_ms": 12, "payload_mean": 3100,
        "payload_std": 40, "senders": 1, "connects_per_s": 0, "malformed": 0, "seq_gaps": 0,
        "seq_repeats": 0, "stale_ms": 140,
    },
    "request": {
        "v": 1, "type": "request", "request_id": "req_000012", "ts": 1792252805000, "by": "staff:priya",
        "action": "ack_alert", "target_id": "al_0042", "bed_id": "B03", "note": "",
    },
    "demo_control": {
        "v": 1, "type": "demo_control", "ts": 1792252800000, "cmd": "run", "run_id": "run_20261017_160000",
        "start_at_s": 0,
    },
    "record": {
        "v": 1, "type": "record", "ts": 1792252806000, "kind": "ticket", "record_id": "tk_0007", "by": "A6",
        "data": {"any": "JSON object"},
    },
}


@pytest.fixture
def example() -> Callable[[str], dict[str, Any]]:
    """Return a factory: example("vitals") gives a deep copy of that contract example."""
    return lambda mtype: copy.deepcopy(EXAMPLES[mtype])
