import {expect, it} from 'vitest';
import type {Action, Device} from './types';
import {hasConfirmedCutOff} from './deviceStatus';

const device: Pick<Device, 'device_id' | 'isolated' | 'isolated_since'> = {device_id: 'MON-05', isolated: true, isolated_since: 1000};
const cut: Action = {id: 'cut', occurred_at: 2000, actor: 'A2', action_code: 'disable_client',
  action: 'Cut off MON-05 at the hub after TAMPERING; session wiped', bed_id: 'B05', device_id: 'MON-05',
  approved_by: null, mode: 'automatic', undoable: true, references_action_id: null};

it('requires an active flag and successful cut-off evidence from its current isolation period', () => {
  expect(hasConfirmedCutOff([cut], device)).toBe(true);
  expect(hasConfirmedCutOff([], device)).toBe(false);
  expect(hasConfirmedCutOff([cut], {...device, isolated: false})).toBe(false);
  expect(hasConfirmedCutOff([cut], {...device, isolated_since: 3000})).toBe(false);
  expect(hasConfirmedCutOff([{...cut, device_id: 'MON-10'}], device)).toBe(false);
});
it.each([
  ['disable_client', 'DRY RUN: would cut off MON-05 after TAMPERING (no hub control configured)'],
  ['disable_client', 'Cut-off of MON-05 FAILED at the hub after TAMPERING; bed stays untrusted'],
  ['isolate_device', 'Requested cut-off of MON-05'],
  ['set_bed_untrusted', 'Bed B05 marked UNTRUSTED'],
])('never treats %s request, failure or simulation as a completed cut-off', (action_code, action) => {
  expect(hasConfirmedCutOff([{...cut, action_code, action}], device)).toBe(false);
});
it('clears a completed cut-off after a later reconnection, but preserves it after a failed reconnection', () => {
  const enable = {...cut, id: 'enable', occurred_at: 3000, action_code: 'enable_client', references_action_id: cut.id,
    action: 'Re-enabled MON-05 at the hub (IT verified); bed B05 trusted again'};
  expect(hasConfirmedCutOff([cut, enable], device)).toBe(false);
  expect(hasConfirmedCutOff([cut, {...enable, action: 'Re-enable of MON-05 FAILED at the hub; still cut off, try again'}], device)).toBe(true);
});
