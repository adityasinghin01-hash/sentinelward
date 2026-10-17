"""Broker sender counts survive the real scoring loop's late five-second tick."""
import json

import pytest

from sw_brain.io import MemoryBus, encode
from sw_brain.service import BrainService
from sw_sec.features import Extractor, LogTail

ORIGIN = 1792261900000


@pytest.mark.parametrize('late_ms', [0, 1, 26, 199, 4999])
@pytest.mark.parametrize('model', ['M4', 'M5'])
def test_completed_broker_sender_window_survives_tick_jitter(tmp_path, frame, late_ms, model):
    path = tmp_path / 'mosquitto.log'
    path.touch()
    extractor = Extractor()
    tail = LogTail(path, extractor, clock=lambda: ORIGIN)
    tail.poll()
    brain = BrainService(MemoryBus())
    # Two publishers take turns in one window, with NO duplicate/regressed
    # frames. Connection alone (including an admin auto-ID) is not a sender.
    with path.open('a') as log:
        log.write("1792261920: New client connected from 127.0.0.1:58906 as auto-A43E (p5, c1, k60, u'admin').\n")
        for sec in range(20, 45):
            at = ORIGIN + sec * 1000
            topic = 'ward/bed/B12/vitals'
            payload = encode(topic, frame(sec, bed='B12', ts=at))
            extractor.observe(topic, payload, at)
            brain.receive(topic, payload, received_ms=at)
            client = 'sw-attacks' if sec == 32 else 'MON-12'
            log.write(f"{at//1000}: Received PUBLISH from {client} (d0, q0, r0, m0, '{topic}', ... ({len(payload)} bytes))\n")
            log.flush()
            tail.poll()
            if sec == 34:
                feature = extractor.snapshot('MON-12', ORIGIN + 30000)
                assert feature['senders'] == 2
                assert feature['seq_repeats'] == 0
                assert feature['seq_gaps'] == 0
                assert brain.receive('net/device/MON-12/features', json.dumps(feature),
                                     received_ms=ORIGIN + 35200)
    score = brain.suite.detectors[model].evaluate(None, brain.beds['B12'], ORIGIN + 40000 + late_ms)
    assert score['extra']['senders'] == 2
    assert score['score'] == .6
    if model == 'M4':
        assert score['extra']['sender_count_available']
        assert not score['extra']['independent_evidence']
        # Aggregate log counts do not identify individual MQTT receipts.
        assert not score['extra']['sender_identity_available']
    else:
        assert score['extra']['sender_identity_available']


def test_b12_broker_identity_alone_holds_unsure_until_patient_ok(tmp_path, frame):
    from tests_system.witness_replay_eval import LogInputs

    bus = MemoryBus()
    brain = BrainService(bus)
    live = LogInputs(brain, path=tmp_path/'mosquitto.log', origin=ORIGIN+1000000, beds=('B12',))
    verdicts = {}
    try:
        for sec in range(1000, 1090):
            now = ORIGIN+sec*1000
            if sec in (1030, 1045, 1080, 1085):
                verdicts[sec] = brain.tick(now+26)[0]
                m4 = next(m for _, m, _, _ in reversed(bus.published) if m.get('model') == 'M4')
                if sec == 1030:
                    assert m4['extra']['senders'] == 2
                    assert m4['extra']['sender_count_available']
                    assert m4['extra']['sequence_events'] == 0
                    assert not m4['extra']['duplicate_only']
                    assert not m4['extra']['independent_evidence']
                    assert verdicts[sec]['scores']['M4'] == .6
                    assert verdicts[sec]['scores']['M5'] == .6
                bus.published.clear()
            if sec == 1080:
                assert brain.receive('ward/bed/B12/bedside', json.dumps(dict(
                    v=1, type='bedside_check', bed_id='B12', ts=now+30,
                    result='patient_ok', by='staff:nurse')), received_ms=now+30)
            topic = 'ward/bed/B12/vitals'
            # Publishers take turns; the full end-to-end decision must use
            # broker identity because every frame has a fresh sequence/ts.
            client = 'sw-attacks' if 1020 <= sec < 1040 and sec % 2 else 'MON-12'
            payload = encode(topic, frame(sec, bed='B12', ts=now))
            assert live.receive(topic, payload, now, client)
            for ms in range(200, 1000, 200):
                live.publish_due(now+ms)
        assert [verdicts[t]['verdict'] for t in (1030, 1045, 1080, 1085)] == [
            'UNSURE', 'UNSURE', 'UNSURE', 'NORMAL']
        assert all(r['sender_id'] is None and not r['sequence_issue'] for r in brain.beds['B12'].messages)
        assert brain.invalid_incoming == brain.invalid_outgoing == 0
    finally:
        live.close()
