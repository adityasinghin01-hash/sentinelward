import {describe, expect, it} from 'vitest';
import type {Action} from '../../lib/types';
import records from './actions.live.json';
import {actionView} from './actions';

// Read-only /api/actions?limit=200 observations, collected over a full restart interval on 18 Oct.
describe('every action code observed in the live demo', () => {
  it.each(records)('$action_code', record => {
    const original = {...record, id: 'audit-test', occurred_at: 1, undoable: false, approved_by: null, references_action_id: null} as Action;
    const before = JSON.stringify(original);
    const view = actionView(Object.freeze(original));
    expect(view.what).not.toBe('Recorded an action');
    expect(`${view.who} ${view.what} ${view.why}`).not.toMatch(/(?:\b(?:al|rp|inc|br|act|cmd)_[a-z0-9_]+|staff:|sha256|\.jsonl?|telegram|patient_ok|set_bed_untrusted|disable_client)/i);
    expect(JSON.stringify(original)).toBe(before);
  });
});
