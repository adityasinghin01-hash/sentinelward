"""Replay the simulator/attacker through a real tailed Mosquitto-format file.

python -m tests_system.witness_replay_eval --output /tmp/witness.json
Adds 26 ms scoring jitter and 200 ms log polling/feature delivery. No broker,
network, or sleeps. Historical log lines are seeded before the tail attaches.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from sw_common import BED_IDS
from sw_sec.features import LogTail
from tests_system.attack_replay_eval import BEDS, LiveInputs, ORIGIN, evaluate, show


class LogInputs(LiveInputs):
    def __init__(self, brain, *, path, origin=ORIGIN, beds=BEDS):
        super().__init__(brain, origin, beds)
        self.path = Path(path)
        self.now = origin
        # A backlog larger than the old 10,000-line budget. These stale senders
        # must never pollute live windows or hold the witness in catch-up mode.
        old = f"{origin//1000-60}: Received PUBLISH from retired-client (d0, q0, r0, m0, 'ward/bed/B12/vitals', ... (2921 bytes))\n"
        self.path.write_text(old*10001)
        self.tail = LogTail(self.path, self.extractor, clock=lambda: self.now)
        self.tail.poll()
        self.next_poll = origin+200
        self.log = self.path.open('a')
        self.log.write(f"{origin//1000}: New client connected from 127.0.0.1:58906 as auto-A43E (p5, c1, k60, u'admin').\n")
        self.windows = {bed: [] for bed in beds}

    def observe(self, topic, payload, at, client):
        self.extractor.observe(topic, payload, at)
        self.log.write(f"{at//1000}: Received PUBLISH from {client} (d0, q0, r0, m0, '{topic}', ... ({len(payload)} bytes))\n")

    def publish_due(self, at):
        if at >= self.next_poll:
            self.now = at
            self.log.flush()
            self.tail.poll()
            self.next_poll = (at//200+1)*200
        if at >= self.next_end+200:
            start = self.next_end-5000
            for bed in self.beds:
                feature = self.extractor.snapshot('MON-'+bed[1:], start)
                self.windows[bed].append([(start-self.origin)//1000, feature['senders']])
        super().publish_due(at)

    def diagnostics(self):
        return {'sender_windows': self.windows, 'caught_up': self.extractor.logs_available,
                'offset': self.tail.offset}

    def close(self):
        self.log.close()


def replay(packs, order='monitor-first', *, tick_jitter_ms=26):
    with tempfile.TemporaryDirectory(prefix='sw-witness-') as folder:
        inputs = []

        def factory(brain, **kwargs):
            live = LogInputs(brain, path=Path(folder)/'mosquitto.log', **kwargs)
            inputs.append(live)
            return live

        try:
            return evaluate(packs, order, live_factory=factory,
                            tick_jitter_ms=tick_jitter_ms, beds=BED_IDS)
        finally:
            for live in inputs:
                live.close()


def compare(results, baseline):
    before = {r['order']: r for r in baseline}
    for run in results:
        previous = before.get(run['order'])
        if previous is None:
            print(f"{run['order']}: no baseline for this arrival order")
            continue
        for bed in BEDS:
            same = run['timelines'][bed] == previous['timelines'][bed]
            print(f"COMPARE {run['order']} {bed}: {'UNCHANGED' if same else 'DIFFERS'}")


def verify(results):
    for run in results:
        windows = run['log_witness']['sender_windows']
        assert run['log_witness']['caught_up']
        for bed in ('B01', 'B02', 'B03', 'B04', 'B08', 'B09'):
            assert max(n for _, n in windows[bed] if n is not None) <= 1, bed
        assert [1020, 2] in windows['B12']
        assert run['checkpoints'][1030]['B12']['verdict'] == 'UNSURE'
        assert run['checkpoints'][1080]['B12']['verdict'] == 'UNSURE'
        assert all(label == 'UNSURE' for t, label in run['timelines']['B12'] if 1030 <= t <= 1080)
        assert run['checkpoints'][1085]['B12']['verdict'] == 'NORMAL'
        for model in ('M4', 'M5'):
            assert run['sender_evidence'][1030]['B12'][model]['extra']['senders'] == 2
        assert run['invalid_messages'] == run['blank_snapshots'] == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packs', type=Path, default=Path.home()/'Desktop/sentinelward/.work/packs-v13')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--order', choices=('both', 'monitor-first', 'attack-first'), default='both')
    parser.add_argument('--tick-jitter-ms', type=int, default=26)
    args = parser.parse_args()
    orders = ('monitor-first', 'attack-first') if args.order == 'both' else (args.order,)
    results = [replay(args.packs, order, tick_jitter_ms=args.tick_jitter_ms) for order in orders]
    args.output.write_text(json.dumps(results, indent=2)+'\n')
    show('LOG-WITNESS', results)
    if args.compare:
        compare(results, json.loads(args.compare.read_text()))
    verify(results)


if __name__ == '__main__':
    main()
