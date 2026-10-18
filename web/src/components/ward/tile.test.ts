import {expect, it} from 'vitest';
import type {Bed} from '../../lib/types';
import {trustView} from '../../lib/domain';
import {tileView} from './tile';

it.each(['DEVICE_ATTACK', 'NORMAL', null] as const)('shows flagged B11 (%s) as untrusted without inventing a completed cut-off', verdict => {
  const bed = {bed_id: 'B11', device_id: 'MON-11', verdict, isolated: true,
    is_trusted: false, connected: true, display: 'last_trusted', last_updated_at: 1000,
    trust_score: 0, last_trusted: null} as Bed;
  const view = tileView(bed, [], 1000);
  expect(`${view.word} ${view.reason} ${view.footer}`).toContain('Data untrusted');
  expect(`${view.word} ${view.reason} ${view.footer} ${trustView(bed).why}`).not.toMatch(/cut off|disconnected|isolated by IT/i);
  expect(view.untrusted).toBe(true);
});

it('keeps the emergency urgent when an isolated flag has no action evidence', () => {
  const bed = {bed_id: 'B07', verdict: 'BOTH', isolated: true, is_trusted: false,
    connected: true, display: 'last_trusted', last_updated_at: 1000, last_trusted: null} as Bed;
  const view = tileView(bed, [], 1000);
  expect(view.group).toBe('emergency');
  expect(view.reason).toContain('Go now');
  expect(view.footer).toBe('Data untrusted · device flagged');
});

it.each([null, {captured_at: 1000}] as const)('keeps the flagged tampering reason once and uses last-good timing in the footer (%j)', last_trusted => {
  const bed = {bed_id: 'B10', verdict: 'TAMPERING', isolated: true, is_trusted: false,
    connected: true, display: 'last_trusted', last_updated_at: 1000, last_trusted} as Bed;
  const view = tileView(bed, [], 4000);
  expect(view.reason).toBe('Data untrusted · device flagged');
  expect(view.footer).toBe(last_trusted ? 'Not trusted · last good 3 s ago' : null);
});

it('distinguishes no data yet from a monitor that stopped sending', () => {
  const bed = {bed_id: 'B03', verdict: null, display: 'empty', connected: true,
    last_updated_at: null, is_trusted: false, last_trusted: null} as Bed;
  expect(tileView(bed, [], 4000)).toMatchObject({word: 'No monitor data yet', reason: 'Waiting for the first reading', footer: null});
  expect(tileView({...bed, display: 'offline', last_updated_at: 1000, connected: false}, [], 8000).reason).toBe('Monitor silent · check by hand');
});
