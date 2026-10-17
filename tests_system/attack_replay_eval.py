"""Offline ward attack replay using production pack building, scheduler and brain.

Run before editing with --output /tmp/m4-before.json; after editing use
--compare /tmp/m4-before.json --output /tmp/m4-after.json. No MQTT or wall sleeps.
Attack-first means the attacker has received the source frame while its delivery
on the brain's monitor connection is delayed by 10 ms. Other packets use 20 ms
scheduler steps; scoring runs on the real five-second grid before new frames.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import tempfile

from sw_attacks.service import AttackService
from sw_brain.io import MemoryBus, encode
from sw_brain.service import BrainService
from sw_common.topics import vitals_topic
from sw_sim.clock import InstantClock
from sw_sim.config import load_script
from sw_sim.engine import WardRun
from sw_sim.packs import load_packs

ROOT = Path(__file__).resolve().parents[1]
BEDS = ('B05', 'B06', 'B07', 'B10', 'B11', 'B12')
ORIGIN = 1800000000000  # aligned to five seconds, same epoch for both runs


class AttackBus(MemoryBus):
    def __init__(self, brain):
        super().__init__()
        self.brain = brain
        self.now = ORIGIN
        self.counts = Counter()
        self.accepted = Counter()

    def publish(self, topic, data, qos=1, retain=False):
        self.counts[data['bed_id']] += 1
        accepted = self.brain.receive(topic, encode(topic, data), received_ms=self.now,
                                      received_mono_ms=self.now-ORIGIN, sender_id='attack-account')
        self.accepted[data['bed_id']] += bool(accepted)
        return True


def evaluate(packs_dir, order):
    script = load_script(ROOT / 'simulator/ward_script.yaml').select(BEDS)
    packs = load_packs(packs_dir, [b.pack_name for b in script.beds])
    clock = InstantClock(ORIGIN)
    run = WardRun(script, packs, run_id='offline', runs_dir='/tmp', clock=clock, bus=None, dry_run=True)
    bus = MemoryBus()
    brain = BrainService(bus)
    attack_bus = AttackBus(brain)
    timelines = {bed: [] for bed in BEDS}
    counts = {bed: Counter() for bed in BEDS}
    monitor = Counter()
    blank = invalid = 0
    with tempfile.TemporaryDirectory(prefix='m4-replay-') as logs:
        attack = AttackService(attack_bus, runs_dir=logs)
        attack.receive('ward/demo/control', json.dumps(dict(v=1, type='demo_control', ts=ORIGIN,
                       cmd='run', run_id='offline', start_at_s=0)), received_ms=ORIGIN)
        for sec in range(script.run_length_s+1):
            now = ORIGIN+sec*1000
            if sec and sec % 5 == 0:
                for verdict in brain.tick(now):
                    bed = verdict['bed_id']; label = verdict['verdict']
                    counts[bed][label] += 1
                    if not timelines[bed] or timelines[bed][-1][1] != label:
                        timelines[bed].append([sec, label])
                    blank += brain.display_snapshot(bed) is None
                bus.published.clear()  # scores are validated by MemoryBus; avoid retaining a run of waveforms
            if sec == 1080:
                bed = 'B12'
                brain.receive(f'ward/bed/{bed}/bedside', json.dumps(dict(v=1, type='bedside_check',
                              bed_id=bed, ts=now, result='patient_ok', by='staff:nurse')), received_ms=now)
            if sec == script.run_length_s:
                break
            _, batch = run._prepare(sec, now)
            for out in batch:
                assert out.message is not None, (sec, out.bed.bed_id)
                topic = vitals_topic(out.bed.bed_id)
                # The attack connection sees the real source independently of brain receipt order.
                attack.receive(topic, encode(topic, out.message), received_ms=now)
            def deliver_monitor(delay):
                for out in batch:
                    topic = vitals_topic(out.bed.bed_id)
                    brain.receive(topic, encode(topic, out.message), received_ms=now+delay,
                                  received_mono_ms=sec*1000+delay, sender_id='monitor-account')
                    monitor[out.bed.bed_id] += 1
            if order == 'monitor-first':
                deliver_monitor(0)
            attack_bus.now = now
            attack.tick(now)
            if order == 'attack-first':
                deliver_monitor(10)
            # Commit simulator sequence counters through its real send path.
            clock.wait_until(now, run._stop)
            run._send(sec, now, batch)
            for ms in range(20, 1000, 20):
                attack_bus.now = now+ms
                attack.tick(now+ms)
        attack.close(ORIGIN+script.run_length_s*1000)
        invalid = brain.invalid_incoming+brain.invalid_outgoing+attack.invalid_incoming+attack.invalid_outgoing
        return dict(order=order, timelines=timelines, verdict_counts=counts, monitor_frames=monitor,
                    attack_frames=attack_bus.counts, accepted_attack_frames=attack_bus.accepted,
                    blank_snapshots=blank, invalid_messages=invalid)


def stamp(sec):
    return f'{sec//60:02d}:{sec%60:02d}'


def show(label, results):
    for run in results:
        print(f"{label} {run['order']} blank={run['blank_snapshots']} invalid={run['invalid_messages']}")
        for bed in BEDS:
            print(bed, ' -> '.join(f'{stamp(t)} {v}' for t, v in run['timelines'][bed]))
            print(' ', dict(run['verdict_counts'][bed]), 'monitor=', run['monitor_frames'][bed],
                  'attack=', run['attack_frames'][bed], 'accepted_attack=', run['accepted_attack_frames'][bed])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packs', type=Path, default=Path.home()/'Desktop/sentinelward/.work/packs-v13')
    parser.add_argument('--order', choices=('both', 'monitor-first', 'attack-first'), default='both')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    if args.compare:
        show('BEFORE', json.loads(args.compare.read_text()))
    orders = ('monitor-first', 'attack-first') if args.order == 'both' else (args.order,)
    results = [evaluate(args.packs, order) for order in orders]
    show('AFTER' if args.compare else 'CURRENT', results)
    if args.output:
        args.output.write_text(json.dumps(results, indent=2)+'\n')


if __name__ == '__main__':
    main()
