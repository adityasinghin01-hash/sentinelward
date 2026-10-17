"""Offline ward attack replay using production pack building, scheduler and brain.

Run before editing with --output /tmp/m4-before.json; after editing use
--compare /tmp/m4-before.json --output /tmp/m4-after.json. No MQTT or wall sleeps.
Attack-first means the attacker has received the source frame while its delivery
on the brain's monitor connection is delayed by 10 ms. Other packets use 20 ms
scheduler steps; scoring runs on the real five-second grid before new frames.
MQTT receipts carry no publisher ID. The real security-v2 Extractor consumes the
same wire payloads and synthetic Mosquitto PUBLISH lines; only its aggregate
net_features reach the brain. Completed windows arrive 200 ms after their end
(one extractor poll), so scoring never sees the just-completed window early.
"""
from __future__ import annotations

import argparse
from collections import Counter
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
from sw_sec.features import Extractor

ROOT = Path(__file__).resolve().parents[1]
BEDS = ('B05', 'B06', 'B07', 'B10', 'B11', 'B12')
ORIGIN = 1800000000000  # aligned to five seconds, same epoch for both runs


class LiveInputs:
    """Real aggregation: features.py:71-100,111-153; cadence: extractor_service.py:39-55.

    Assumes healthy subscription/log coverage after the initial partial window,
    no loss, and one 200 ms poll of publication latency. Client IDs are used only
    in broker log lines, never in brain receipts or vitals payloads.
    """
    def __init__(self, brain, origin=ORIGIN, beds=BEDS):
        self.brain = brain
        self.origin = origin
        self.beds = beds
        self.extractor = Extractor()
        self.extractor.logs_available = True
        self.extractor.log_coverage_start = origin+5000
        self.next_end = origin+5000
        self.published = Counter()

    def observe(self, topic, payload, at, client):
        self.extractor.observe(topic, payload, at)
        self.extractor.log(f"{at//1000}: Received PUBLISH from {client} (d0, q0, r0, m0, '{topic}', ... ({len(payload)} bytes))")

    def receive(self, topic, payload, at, client):
        self.observe(topic, payload, at, client)
        return self.brain.receive(topic, payload, received_ms=at,
                                  received_mono_ms=at-self.origin, sender_id=None)

    def publish_due(self, at):
        if at < self.next_end+200:
            return
        start = self.next_end-5000
        for bed in self.beds:
            device = 'MON-'+bed[1:]
            message = self.extractor.snapshot(device, start)
            # extractor_service.py:49-52: startup partial receive coverage is unknown.
            if start < self.origin+5000:
                for key in message:
                    if key not in ('v','type','device_id','window_start','window_s'):
                        message[key] = None
            topic = f'net/device/{device}/features'
            assert self.brain.receive(topic, encode(topic, message), received_ms=at)
            self.published[bed] += 1
        self.next_end = (at//5000+1)*5000


class AttackBus(MemoryBus):
    def __init__(self, live):
        super().__init__()
        self.live = live
        self.now = ORIGIN
        self.counts = Counter()
        self.accepted = Counter()

    def publish(self, topic, data, qos=1, retain=False):
        self.counts[data['bed_id']] += 1
        accepted = self.live.receive(topic, encode(topic, data), self.now, 'sw-attacks')
        self.accepted[data['bed_id']] += bool(accepted)
        return True


def evaluate(packs_dir, order):
    script = load_script(ROOT / 'simulator/ward_script.yaml').select(BEDS)
    packs = load_packs(packs_dir, [b.pack_name for b in script.beds])
    clock = InstantClock(ORIGIN)
    run = WardRun(script, packs, run_id='offline', runs_dir='/tmp', clock=clock, bus=None, dry_run=True)
    bus = MemoryBus()
    brain = BrainService(bus)
    live = LiveInputs(brain)
    attack_bus = AttackBus(live)
    timelines = {bed: [] for bed in BEDS}
    counts = {bed: Counter() for bed in BEDS}
    monitor = Counter()
    blank = invalid = 0
    checkpoints = {}
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
                    if sec in (730, 740, 830, 835, 840, 845, 1025, 1045, 1080, 1085, 1090):
                        checkpoints.setdefault(sec, {})[bed] = verdict
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
                    payload = encode(topic, out.message)
                    # The independent extractor sees the broker's source first;
                    # only the brain monitor connection is delayed in attack-first.
                    if delay:
                        brain.receive(topic, payload, received_ms=now+delay,
                                      received_mono_ms=sec*1000+delay, sender_id=None)
                    else:
                        live.receive(topic, payload, now, out.message['device_id'])
                    monitor[out.bed.bed_id] += 1
            if order == 'monitor-first':
                deliver_monitor(0)
            else:
                for out in batch:
                    live.observe(vitals_topic(out.bed.bed_id), encode(vitals_topic(out.bed.bed_id), out.message),
                                 now, out.message['device_id'])
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
                live.publish_due(now+ms)
        attack.close(ORIGIN+script.run_length_s*1000)
        invalid = brain.invalid_incoming+brain.invalid_outgoing+attack.invalid_incoming+attack.invalid_outgoing
        return dict(order=order, timelines=timelines, verdict_counts=counts, monitor_frames=monitor,
                    attack_frames=attack_bus.counts, accepted_attack_frames=attack_bus.accepted,
                    net_feature_windows=live.published, checkpoints=checkpoints,
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
