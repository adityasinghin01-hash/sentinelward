import math

import pytest

torch = pytest.importorskip('torch')

from sw_chip.model import ChipModel, MODEL_NAME, STATE_SHA256  # noqa: E402

KEYS = {'v', 'bed_id', 'ts', 'alarm_code', 'p_real', 'label', 'threshold', 'model', 'device', 'latency_ms',
        'heldout_challenge_cinc', 'heldout_challenge_vtac'}


@pytest.fixture(scope='module')
def model():
    return ChipModel(device='cpu')


def window(missing_ppg=False, abp=False):
    ecg = [math.sin(2 * math.pi * 1.3 * i / 125) ** 15 for i in range(1250)]
    ppg = [None] * 1250 if missing_ppg else [50 + 10 * math.sin(2 * math.pi * 1.3 * i / 125) for i in range(1250)]
    return {'ecg': ecg, 'ppg': ppg, 'abp': [80.0 + (i % 100) / 10 for i in range(1250)] if abp else None}


def test_hash_pinned_and_checked(tmp_path, model):
    assert model.sha256 == STATE_SHA256
    bad = tmp_path / 'bad.pt'
    bad.write_bytes(b'x')
    with pytest.raises(ValueError, match='SHA-256'):
        ChipModel(device='cpu', state=bad)


def test_message_matches_contract(model):
    m = model.message('B03', 1760000010000, 'VTACH', window())
    assert set(m) == KEYS
    assert m['v'] == 1 and m['bed_id'] == 'B03' and m['alarm_code'] == 'VTACH' and m['model'] == MODEL_NAME
    assert 0 <= m['p_real'] <= 1 and m['device'] == 'cpu' and m['latency_ms'] > 0
    assert m['label'] == ('real' if m['p_real'] >= m['threshold'] else 'false')
    assert m['threshold'] == round(model.thresholds['VTACH'], 4)
    assert (m['heldout_challenge_cinc'], m['heldout_challenge_vtac']) == (0.623, 0.665)


@pytest.mark.parametrize('code', ['ASYSTOLE', 'BRADY', 'TACHY', 'VFIB', 'VTACH'])
def test_every_alarm_type_and_missing_channels(model, code):
    for w in (window(), window(missing_ppg=True), window(abp=True)):
        p, ms = model.predict(w, code)
        assert 0 <= p <= 1


def test_unknown_code_and_bad_length(model):
    with pytest.raises(ValueError):
        model.predict(window(), 'NOPE')
    with pytest.raises(ValueError):
        model.predict({'ecg': [0.0] * 10, 'ppg': None, 'abp': None}, 'VTACH')


def test_cpu_forced_even_if_nnpa_present():
    assert ChipModel(device='cpu').device == 'cpu'
