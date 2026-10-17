import {expect, it} from 'vitest';
import type {Action} from '../../lib/types';
import {actionView} from './actions';
const event = (action_code: string, action: string, extra: Partial<Action> = {}): Action => ({
  id: 'event', occurred_at: 1000, actor: 'A1', action_code, action, bed_id: 'B07', device_id: 'MON-07',
  mode: 'automatic', undoable: false, approved_by: null, references_action_id: null, ...extra,
});
it.each([
  ['escalate', 'Alert al_x: no acknowledgement for 30 s; step 3 -> staff:dr_mehta; telegram queued', 'B07 · No one acknowledged in 30 s — Dr Mehta paged (Telegram queued)'],
  ['write_briefing', 'Briefing br_x (periodic) written by template; template because: Granite still writing', 'Shift briefing updated (template; Granite busy)'],
  ['set_watch_level', "Watch level HIGH for 11 'demo-monitor' devices until 03:09 (bookkeeping; IT decides any cut-off)", 'Extra watch on 11 demo monitors until 03:09'],
  ['edit_message', 'IT message updated: Device cut off 02:08:45; bed marked untrusted.; telegram IT group queued', 'B07 · IT update: MON-07 cut off — data untrusted (Telegram queued)'],
  ['list_devices', "Fleet hunt after MON-07 was cut off: model 'demo-monitor': 11 devices (MON-01..MON-12). Check next: none flagged (all NORMAL and trusted)", 'Checked 11 other monitors after MON-07 cut-off: none flagged'],
] as const)('formats %s as a factual nurse-readable sentence', (code, raw, expected) => {
  expect(actionView(event(code, raw, ['write_briefing', 'set_watch_level', 'list_devices'].includes(code) ? {bed_id: null, device_id: null} : {})).summary).toBe(expected);
});
it('does not turn missing fleet verdicts into an all-clear', () => {
  const raw = "Fleet hunt after MON-10 was cut off: model 'demo-monitor': 11 devices (MON-01..MON-12). Check next: MON-03 (no verdict yet), MON-04 (no verdict yet)";
  expect(actionView(event('list_devices', raw, {bed_id: null, device_id: null})).summary).toBe('Checked 11 other monitors after MON-10 cut-off: follow-up needed on MON-03, MON-04');
});
it('does not call an expired watch an increase', () => {
  expect(actionView(event('set_watch_level', "Watch level back to normal for 11 'demo-monitor' devices (expired)", {bed_id: null})).summary).toBe('Extra watch ended for 11 demo monitors');
});
it('does not imply Telegram delivery when only queued, or add a channel without evidence', () => {
  expect(actionView(event('escalate', 'Alert al_x: no acknowledgement for 30 s; step 3 -> staff:dr_mehta')).summary).toBe('B07 · No one acknowledged in 30 s — alert for Dr Mehta');
});
it('does not repeat an absent reason in an unknown event summary', () => {
  expect(actionView(event('new_code', 'private raw text')).summary).toBe('B07 · Action recorded — see Details');
});
it.each([
  ['record_ack', 'Alert al_x acknowledged by staff:priya via telegram after 12.5 s (step 2); telegram queued', 'B07 · Alert acknowledged by Priya'],
  ['record_ack', 'Acknowledgement of al_x withdrawn by staff:priya; alert re-opened, ladder restarted', 'B07 · Acknowledgement withdrawn — alert open again'],
  ['warn_workload', 'To staff:priya: staff:tom received 44 alarms in the last 2 h (limit 40); consider moving a bed to staff:priya (12 alarms). Charge nurse decides.', 'Tom received 44 alarms in 2 h — charge nurse review needed'],
  ['warn_workload', 'Workload warning for staff:tom withdrawn by staff:priya', 'Workload warning for Tom withdrawn'],
  ['write_briefing', 'Briefing br_x (periodic) written by template; template because: Granite busy with an earlier briefing', 'Shift briefing updated (template; Granite busy)'],
  ['write_briefing', 'Briefing br_x (periodic) written by template; template because: SW_GRANITE_URL not set', 'Shift briefing updated (template; Granite unavailable)'],
  ['write_briefing', 'Briefing br_x (periodic) refreshed by IBM Granite in 23 s', 'Shift briefing updated (IBM Granite)'],
  ['escalate', 'Alert al_x: no acknowledgement for 30 s; step 3 -> same people', 'B07 · No one acknowledged in 30 s — alert escalated to step 3'],
] as const)('explains the agent record %s without inventing a recipient or outcome', (code, raw, expected) => {
  expect(actionView(event(code, raw, ['warn_workload', 'write_briefing'].includes(code) ? {bed_id: null, device_id: null} : {})).summary).toBe(expected);
});
it.each([
  ['escalate', 'Alert al_x: no acknowledgement for 30 s; step 3 -> staff:dr_mehta; telegram off', 'B07 · No one acknowledged in 30 s — alert for Dr Mehta (screen only)'],
  ['escalate', 'Alert al_x: no acknowledgement for 30 s; step 3 -> staff:priya, staff:dr_mehta; telegram queued for staff:priya; no chat for staff:dr_mehta', 'B07 · No one acknowledged in 30 s — Telegram queued for Priya; no Telegram chat for Dr Mehta'],
  ['send_message', 'Alert al_x (EMERGENCY, high) step 1 -> staff:tom; telegram queued for nobody; no chat for staff:tom', 'B07 · No Telegram chat for Tom — alert on screen only'],
  ['edit_message', 'IT message updated: Device cut off 02:08:45; bed marked untrusted.; telegram off or no IT chat: Security screen only', 'B07 · IT update: MON-07 cut off — data untrusted (Security screen only)'],
  ['send_message', 'IT notified: MON-07 TAMPERING; telegram off or no IT chat: Security screen only', 'B07 · IT alert for MON-07 (Security screen only)'],
] as const)('preserves screen-only or partial notification outcomes for %s', (code, raw, expected) => {
  expect(actionView(event(code, raw)).summary).toBe(expected);
});
it('keeps the same notification limits when the formatter is used by an incident timeline', () => {
  const view = actionView(event('send_message', 'Alert al_x (EMERGENCY, high) step 1 -> staff:tom; telegram off'));
  expect(view.what).toBe('Alert for Tom (screen only)');
});
it.each([
  ['disable_client', 'DRY RUN: would cut off MON-07 after TAMPERING (no hub control configured)', 'B07 · Simulated cut-off of MON-07'],
  ['disable_client', 'Cut-off of MON-07 FAILED at the hub after TAMPERING; bed stays untrusted', 'B07 · Could not cut off MON-07'],
  ['isolate_device', 'Requested isolation of MON-07', 'B07 · Requested cut-off of MON-07'],
] as const)('distinguishes a completed hub action from %s request/failure/simulation', (code, raw, expected) => {
  expect(actionView(event(code, raw)).summary).toBe(expected);
});
it.each([
  ['IT message updated: DRY RUN: device would be cut off (02:08:45); bed marked untrusted.; telegram IT group queued', 'B07 · IT update: MON-07 cut-off simulated — data untrusted (Telegram queued)'],
  ['IT message updated: Device not cut off.; telegram IT group queued', 'B07 · IT update: MON-07 not cut off (Telegram queued)'],
  ['IT message updated: Cut-off FAILED at the hub (02:08:45); bed marked untrusted.; telegram IT group queued', 'B07 · IT update: MON-07 cut-off failed — data untrusted (Telegram queued)'],
  ['IT message updated: Bed marked untrusted (02:08:45); device still connected so a real alarm gets through (cut-off if the attack holds 20 s, at once on BOTH).; telegram IT group queued', 'B07 · IT update: MON-07 still connected — data untrusted (Telegram queued)'],
] as const)('keeps the IT containment update factual: %s', (raw, expected) => {
  const view = actionView(event('edit_message', raw));
  expect(view.summary).toBe(expected);
  expect(view.why).not.toBe('Monitor has been cut off');
});
it.each([
  ['DRY RUN: would re-enable MON-07 (demo reset); bed B07 trusted again', 'B07 · Simulated reconnection of MON-07'],
  ['Re-enable of MON-07 FAILED at the hub (IT checked); still cut off, try again', 'B07 · Could not reconnect MON-07'],
  ['Bed B07 trusted again (demo reset); MON-07 had not been cut off at the hub', 'B07 · Restored trusted readings — no hub reconnection needed'],
] as const)('does not invent a successful reconnection: %s', (raw, expected) => {
  expect(actionView(event('enable_client', raw)).summary).toBe(expected);
});
