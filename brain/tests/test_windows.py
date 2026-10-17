from copy import deepcopy

import pytest

from sw_brain.windows import VitalsWindowAssembler


def test_ten_second_windows_overlap_by_five_seconds_and_keep_nulls_alarms(frame):
    assembler = VitalsWindowAssembler()
    outputs = []
    for second in range(20):
        message = frame(second, abp=[80 + second] * 125)
        if second == 6:
            message['ecg'][3] = None
            message['ppg'] = None
            message['monitor_alarm'] = {'code': 'VTACH', 'priority': 'high'}
        window = assembler.ingest(message)
        message['ecg'] = [999] * 125
        if window is not None:
            outputs.append(window)
    assert [w['window_start'] for w in outputs] == [0, 5000, 10000]
    first, overlapping, _ = outputs
    assert first['ecg'][753] is None and not first['ecg_valid'][753]
    assert first['ppg'][750:875] == [None] * 125
    assert first['monitor_alarms'] == [{'code': 'VTACH', 'priority': 'high'}]
    assert overlapping['ecg'][:625] == first['ecg'][625:]
    assert first['abp'][:125] == [80] * 125
    assert (first['seq_first'], first['seq_last']) == (0, 9)
    assert first['window_s'] == 10 and first['sample_rate_hz'] == 125
    first['monitor_alarms'][0]['code'] = 'BRADY'
    assert overlapping['monitor_alarms'][0]['code'] == 'VTACH'


@pytest.mark.parametrize('gap', ['seq', 'ts', 'both'])
def test_gap_discards_partial_history_and_rewarms(frame, gap):
    assembler = VitalsWindowAssembler()
    for second in range(9):
        assert assembler.ingest(frame(second)) is None
    outputs = []
    for second in range(10, 20):
        message = frame(second, seq=second + (1 if gap == 'seq' else 0),
                        ts=(second - (1 if gap == 'seq' else 0)) * 1000)
        if gap == 'ts':
            message['seq'] -= 1
        window = assembler.ingest(message)
        if window:
            outputs.append(window)
    # A sequence-only gap ends off the epoch grid, so needs another chunk.
    if gap == 'seq':
        assert not outputs
        outputs.append(assembler.ingest(frame(20, seq=21, ts=19000)))
    assert len(outputs) == 1
    assert outputs[0]['window_start'] == 10000


@pytest.mark.parametrize('changes', [{'seq': 8}, {'ts': 8000}, {'seq': 2, 'ts': 2000}])
def test_rejected_repeats_do_not_poison_pending_history(frame, changes):
    assembler = VitalsWindowAssembler()
    for second in range(9):
        assembler.ingest(frame(second))
    with pytest.raises(ValueError):
        assembler.ingest(frame(9, **changes))
    assert assembler.ingest(frame(9))['window_start'] == 0


def test_device_change_and_reset_drop_history_and_allow_new_sequences(frame):
    assembler = VitalsWindowAssembler()
    for second in range(9):
        assembler.ingest(frame(second))
    for second in range(10):
        output = assembler.ingest(frame(second, device_id='MON-02'))
        assert (output is not None) == (second == 9)
    assert output['device_id'] == 'MON-02'
    assembler.reset()
    for second in range(10):
        output = assembler.ingest(frame(second))
        assert (output is not None) == (second == 9)


def test_beds_are_independent_and_unaligned_start_waits_for_epoch_boundary(frame):
    assembler = VitalsWindowAssembler()
    outputs = []
    for second in range(2, 15):
        for bed in ('B01', 'B02'):
            output = assembler.ingest(frame(second, bed=bed))
            if output:
                outputs.append((output['bed_id'], output['window_start']))
    assert outputs == [('B01', 5000), ('B02', 5000)]


@pytest.mark.parametrize('changes', [{'ts': 1}, {'fs': 250}, {'seq': -1}, {'seq': True},
                                  {'ecg': [0]}, {'ppg': [float('nan')] * 125},
                                  {'monitor_alarm': {'code': 'unknown', 'priority': 'high'}}])
def test_invalid_chunks_do_not_advance_state(frame, changes):
    assembler = VitalsWindowAssembler()
    for second in range(9):
        assembler.ingest(frame(second))
    with pytest.raises(ValueError):
        assembler.ingest(frame(9, **deepcopy(changes)))
    assert assembler.ingest(frame(9))['seq_last'] == 9
