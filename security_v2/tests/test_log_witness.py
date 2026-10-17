"""Real Mosquitto lines, live append races and bounded startup/rotation."""
import os

from sw_sec.features import Extractor, LogTail

ORIGIN = 1792261900000
PUBLISH = "1792262063: Received PUBLISH from MON-11 (d0, q0, r0, m0, 'ward/bed/B11/vitals', ... (2921 bytes))\n"


def test_first_poll_skips_large_history_and_follows_new_publishers(tmp_path):
    path = tmp_path / 'mosquitto.log'
    path.write_text(PUBLISH * 10001)
    e = Extractor()
    tail = LogTail(path, e, clock=lambda: ORIGIN)
    tail.poll()
    assert e.logs_available
    assert tail.offset == path.stat().st_size
    # Historical publishers must not establish live sender evidence.
    assert e.snapshot('MON-11', 1792262060000)['senders'] == 0
    with path.open('a') as log:
        log.write(PUBLISH)
    tail.poll()
    assert e.snapshot('MON-11', 1792262060000)['senders'] == 1


def test_append_after_stat_does_not_mark_a_complete_read_unavailable(tmp_path, monkeypatch):
    path = tmp_path / 'mosquitto.log'
    path.touch()
    e = Extractor()
    tail = LogTail(path, e, clock=lambda: ORIGIN)
    tail.poll()
    with path.open('a') as log:
        log.write(PUBLISH)
    original = os.fstat
    appended = False

    def fstat(fd):
        nonlocal appended
        info = original(fd)
        if not appended and (info.st_dev, info.st_ino) == (path.stat().st_dev, path.stat().st_ino):
            appended = True
            with path.open('a') as log:
                log.write(PUBLISH.replace('MON-11', 'sw-attacks'))
        return info

    monkeypatch.setattr(os, 'fstat', fstat)
    tail.poll()
    assert e.logs_available
    # Either a fixed-size read or a read through EOF may be used; after the
    # next poll both complete real PUBLISH lines must be available.
    tail.poll()
    assert e.logs_available
    assert e.snapshot('MON-11', 1792262060000)['senders'] == 2


def test_only_publish_topics_attribute_monitor_and_auto_client_ids(tmp_path):
    path = tmp_path / 'mosquitto.log'
    path.touch()
    e = Extractor()
    tail = LogTail(path, e, clock=lambda: ORIGIN)
    tail.poll()
    with path.open('a') as log:
        log.write("1792261920: New client connected from 127.0.0.1:58906 as auto-A43E (p5, c1, k60, u'admin').\n")
        log.write(PUBLISH)
        log.write(PUBLISH.replace('MON-11', 'MON-12').replace('B11', 'B12'))
        log.write(PUBLISH.replace('MON-11', 'sw-attacks').replace('B11', 'B12'))
        log.write(PUBLISH.replace('MON-11', 'sw-attacks').replace('Received', 'Sending'))
        log.write(PUBLISH.replace('MON-11', 'auto-A43E').replace('B11/vitals', 'B12/bedside'))
    tail.poll()
    assert e.snapshot('MON-11', 1792262060000)['senders'] == 1
    assert e.snapshot('MON-12', 1792262060000)['senders'] == 2
    assert e.snapshot('MON-01', 1792262060000)['senders'] == 0
    assert e.snapshot('MON-11', 1792261920000)['senders'] == 0
    # Copy-truncate starts a partial window; full following windows recover.
    tick = 1792262064000
    tail.clock = lambda: tick
    path.write_text('1792262064: broker log reopened\n')
    tail.poll()
    assert e.snapshot('MON-11', 1792262060000)['senders'] is None
    with path.open('a') as log:
        log.write(PUBLISH.replace('1792262063', '1792262065'))
        log.write(PUBLISH.replace('1792262063', '1792262065').replace('MON-11', 'auto-A43E'))
    tail.poll()
    assert e.snapshot('MON-11', 1792262065000)['senders'] == 2


def test_partial_line_is_consumed_only_after_newline(tmp_path):
    path = tmp_path / 'mosquitto.log'
    path.touch()
    e = Extractor()
    tail = LogTail(path, e, clock=lambda: ORIGIN)
    tail.poll()
    path.write_text(PUBLISH[:-10])
    tail.poll()
    assert not e.logs_available
    with path.open('a') as log:
        log.write(PUBLISH[-10:])
    tail.poll()
    assert e.logs_available
    assert e.snapshot('MON-11', 1792262060000)['senders'] == 1
