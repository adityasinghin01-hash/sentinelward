import {describe, expect, it} from 'vitest';
import {timelineView} from './timeline';

describe('incident timeline in words', () => {
  it('keeps the meaning and agent of legacy kind-only events', () => {
    expect(timelineView({ts: 123, agent: 'A2', kind: 'disable_client'}, 'B11', 'MON-11')).toMatchObject({what: 'Cut off MON-11 at the hub', who: 'Network agent', kind: 'agent'});
  });
  it('keeps legacy verdict entries readable', () => {
    expect(timelineView({ts: 123, kind: 'verdict', verdict: 'TAMPERING'}, 'B11', 'MON-11')).toMatchObject({what: 'Decision: Data untrusted (possible tampering)', who: 'Signal checks', kind: 'verdict'});
  });
  it.each([
    ['A1 send_message: Alert al_private (TAMPERING, medium) step 1 -> staff:tom; telegram queued', 'Paged Tom (step 1)', 'Alert agent'],
    ['A2 disable_client: Cut off MON-11 at the hub after TAMPERING', 'Cut off MON-11 at the hub', 'Network agent'],
    ['Detected: TAMPERING (conf 0.95)', 'Detected possible monitor tampering', 'Signal checks'],
    ['Last trusted data (verdict.last_trusted_ts)', 'Last trusted signal received', 'Signal checks'],
    ['Alert al_private open (step 2, medium)', 'Opened the alert · step 2 of 3', 'Alert agent'],
    ['Bedside check: patient_ok by staff:priya', 'Patient checked: patient OK', 'Priya'],
  ])('%s', (event, what, who) => {
    const view = timelineView({ts: 123, event}, 'B11', 'MON-11');
    expect(view).toMatchObject({ts: 123, what, who});
    expect(view.raw).toEqual({ts: 123, event});
    expect(view.what).not.toMatch(/al_|TAMPERING|staff:|\.last_trusted_ts|telegram/);
  });
});
