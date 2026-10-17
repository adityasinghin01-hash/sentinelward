import {describe, expect, it} from 'vitest';
import type {Action} from '../../lib/types';
import {actionView, actorName} from './actions';

const action = (code: string, text: string, extra: Partial<Action> = {}): Action => ({
  id: 'act_private', occurred_at: 1, actor: 'A1', action_code: code, action: text,
  bed_id: 'B06', device_id: 'MON-06', mode: 'automatic', undoable: false,
  approved_by: null, references_action_id: null, ...extra,
});
const cases = [
  ['disable_client', 'Cut off MON-06 at the hub after BOTH (conf 1.00); session wiped', 'Cut off MON-06 at the hub'],
  ['draft_report', 'CERT-In draft rp_abc for incident inc_abc; 8 fields need a person; never sent automatically', 'Drafted the CERT-In report'],
  ['escalate', 'Alert al_abc: no acknowledgement for 30 s; step 3 -> staff:dr_mehta; telegram queued', 'Paged Dr Mehta (step 3)'],
  ['enable_client', 'Re-enabled MON-06 at the hub (demo reset); bed B06 trusted again', 'Reconnected MON-06 at the hub'],
  ['enable_client', 'act_abc undone together with act_def (same release, no second hub change)', 'Recorded the earlier reconnection'],
  ['edit_message', 'IT message updated: Device cut off 02:08:45; bed marked untrusted.; telegram IT group queued', 'Updated IT security'],
  ['hash_file', 'inc_abc/messages.jsonl: 4200 bytes, sha256 abc123', 'Fingerprinted the signal record'],
  ['hash_file', 'inc_abc/verdicts.jsonl: 794 bytes, sha256 abc123', 'Fingerprinted the decision record'],
  ['hash_file', 'inc_abc/timeline.json: 607 bytes, sha256 abc123', 'Fingerprinted the event timeline'],
  ['list_devices', "Fleet hunt after MON-06 was cut off: model 'demo-monitor': 11 devices (MON-01..MON-12).", 'Checked 11 monitors across the ward'],
  ['send_message', 'Alert al_abc (TAMPERING, medium) step 1 -> staff:tom; telegram queued', 'Paged Tom (step 1)'],
  ['send_message', 'Alert al_abc: no acknowledgement for 30 s; step 3 -> staff:dr_mehta; telegram queued', 'Paged Dr Mehta (step 3)'],
  ['send_message', 'IT notified: MON-06 TAMPERING; telegram IT group queued', 'Notified IT security'],
  ['set_bed_untrusted', 'Bed B06 marked UNTRUSTED (TAMPERING (conf 0.98)); last trusted values stay on screen', 'Marked readings as not trusted'],
  ['set_watch_level', "Watch level HIGH for 11 'demo-monitor' devices until 03:09 (bookkeeping; IT decides any cut-off)", 'Raised watch on 11 monitors'],
  ['capture_evidence', 'Manual snapshot of B06', 'Captured a bedside snapshot'],
  ['snapshot_files', 'Incident inc_abc: froze 9 messages (last 10 min) of B06 into 3 files', 'Sealed 10 min of evidence'],
  ['start_clock', 'CERT-In 6 h clock for rp_abc: deadline 08:08 (2026-10-18T02:38:45.015Z)', 'Started the 6-hour report clock'],
  ['write_briefing', 'Briefing br_abc (periodic) kept by template; template because: Granite output rejected: mentions MON-11 which is not in the facts', 'Updated the handover briefing'],
  ['write_timeline', 'Incident inc_abc timeline started with 4 events', 'Started the incident timeline'],
] as const;

describe('plain-language action records', () => {
  it.each(cases)('%s: %s', (code, raw, expected) => {
    const v = actionView(action(code, raw));
    expect(v.what).toBe(expected);
    expect(v.bed).toBe('B06');
    expect(v.why.length).toBeGreaterThan(0);
    expect(`${v.who} ${v.what} ${v.why}`).not.toMatch(/(?:al_|rp_|inc_|br_|staff:|sha256|\.json|telegram|TAMPERING|BOTH|conf \d)/i);
  });
  it('never promotes unknown raw content into the sentence', () => {
    const v = actionView(action('new_code', 'cmd_secret patient_ok record/messages.jsonl sha256 abc'));
    expect(v.what).toBe('Recorded an action');
    expect(v.why).toBe('Reason not recorded · see Details');
  });
  it('uses person names and separates IT from people and agents', () => {
    expect(actorName('A2')).toBe('Network agent');
    expect(actionView(action('capture_evidence', 'Manual snapshot of B06', {actor: 'staff:sam', mode: 'person'}))).toMatchObject({who: 'Sam', kind: 'it'});
    expect(actionView(action('x', '', {actor: 'staff:dr_mehta', mode: 'person'}))).toMatchObject({who: 'Dr Mehta', kind: 'people'});
    expect(actionView(action('x', '', {actor: 'staff:it', mode: 'person'}))).toMatchObject({who: 'IT security', kind: 'it'});
    expect(actionView(action('x', '', {actor: 'A3'})).kind).toBe('agents');
  });
  it('does not mistake the policy for cutting off an emergency for an actual emergency', () => {
    expect(actionView(action('set_bed_untrusted', 'Bed B06 marked UNTRUSTED (TAMPERING (conf 0.98)); device stays connected until the attack holds 20 s (at once on BOTH)')).why).toBe('Monitor may be hacked');
  });
  it('keeps an absent reason honest and does not infer a clinical event', () => {
    expect(actionView(action('disable_client', 'Cut off MON-06 at the hub')).why).toBe('Reason not recorded · see Details');
  });
});
