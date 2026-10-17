import {describe, it, expect} from 'vitest';
import {certDeadline, evidenceView, isAckedAlert, isAutoClosedAlert, openAlerts, reportValue, timelineRow, trustView, verdictTrust, verdictView} from './domain';
import type {Alert, AgentRecord, BedDetail, Score} from './types';

const live = {isolated: false, connected: true, display: 'live' as const, verdict: 'NORMAL' as const, trust_score: 86};
const m2 = (score: number | null, extra: Record<string, unknown> = {}): Score => ({score, reason: 'm2 reason', label: 'real_emergency', extra});

describe('data trust display', () => {
  it('shows the number for a live, checked monitor', () => expect(trustView(live)).toMatchObject({value: 0.86, text: '0.86'}));
  it('never shows 1.00 for a cut-off monitor', () => expect(trustView({...live, isolated: true, trust_score: 100})).toMatchObject({value: null, text: 'not trusted'}));
  it('never shows 1.00 for an offline monitor', () => expect(trustView({...live, connected: false, display: 'offline', trust_score: 100})).toMatchObject({value: null, text: 'not trusted'}));
  it('shows a dash before the first verdict', () => expect(trustView({...live, verdict: null, display: 'empty', trust_score: 0}).text).toBe('—'));
  it('hides trust on verdicts made after the cut-off only', () => {
    const bed = {isolated: true, connected: false, display: 'offline' as const, offline_since: 900, device: {isolated_since: 1000}};
    expect(verdictTrust(1, 1500, bed)).toBe('not trusted');
    expect(verdictTrust(0.8, 500, bed)).toBe('0.80');
  });
});

describe('hero verdict wording', () => {
  const base = {reason: '', isolated: false, connected: true, display: 'live' as const, recent_verdicts: [] as BedDetail['recent_verdicts']};
  it('BOTH says emergency on an attacked monitor, never just "Real emergency"', () => {
    const v = verdictView({...base, verdict: 'BOTH', scores: {}});
    expect(v.headline).toBe('Emergency alarm on an attacked monitor — go now, check by hand; numbers not trusted');
    expect(v.showConfidence).toBe(false);
  });
  it('EMERGENCY shows the monitor alarm code and M2 against its threshold', () => {
    const v = verdictView({...base, verdict: 'EMERGENCY', scores: {M2: m2(0.2708, {alarm_code: 'VTACH', threshold: 0.1658})}});
    expect(v.alarm).toBe('Monitor alarm: VTACH');
    expect(v.aiCheck).toBe('AI check: likely real (score 0.27, threshold 0.17)');
    expect(v.showConfidence).toBe(false);
    expect(verdictView({...base, verdict: 'EMERGENCY', scores: {M2: m2(0.05, {alarm_code: 'ASYSTOLE', threshold: 0.3})}}).aiCheck).toBe('AI check: likely false (score 0.05, threshold 0.30)');
  });
  it('EMERGENCY with no M2 score says so, and uses the monitor alarm from the bed', () => {
    const v = verdictView({...base, verdict: 'EMERGENCY', scores: {M2: m2(null)}, monitor_alarm: {code: 'ASYSTOLE', priority: 'high'}});
    expect(v.alarm).toBe('Monitor alarm: ASYSTOLE');
    expect(v.aiCheck).toBe('AI check: not available (m2 reason)');
  });
  it('EMERGENCY on a cut-off monitor reads as an attacked monitor', () =>
    expect(verdictView({...base, verdict: 'EMERGENCY', isolated: true, connected: false, display: 'offline', scores: {}}).headline).toContain('attacked monitor'));
  it('UNSURE shows the blocking check from the API', () => {
    const v = verdictView({...base, verdict: 'UNSURE', recent_verdicts: [{reasons: ['Body-match check: ECG rate 96 bpm differs from pulse rate 47 bpm']}] as BedDetail['recent_verdicts'], scores: {}});
    expect(v.why).toBe('Blocked by: Body-match check: ECG rate 96 bpm differs from pulse rate 47 bpm');
  });
});

describe('alert counting', () => {
  const a = (status: string, acked_by: string | null = null) => ({alert_id: status + acked_by, status, acked_by, priority: 'medium'} as Alert);
  it('one open definition, and auto-closed alerts are not acknowledged', () => {
    const list = [a('open'), a('escalated'), a('acked', 'staff:priya'), a('closed'), a('closed', 'staff:tom')];
    expect(openAlerts(list)).toHaveLength(2);
    expect(list.filter(isAckedAlert)).toHaveLength(2);
    expect(list.filter(isAutoClosedAlert)).toHaveLength(1);
  });
});

describe('incident and CERT-In mapping', () => {
  const rec = (data: Record<string, unknown>, ts = 1): AgentRecord => ({record_id: 'r', kind: 'report', ts, by: 'A5', version: 1, data, updated_ts: null, updated_by: null});
  it('maps A3 timeline events to agent and text', () => {
    expect(timelineRow({ts: 5, event: 'A2 disable_client: Cut off MON-11 at the hub'})).toEqual({ts: 5, who: 'A2', what: 'Cut off MON-11 at the hub'});
    expect(timelineRow({ts: 6, event: 'Detected: TAMPERING (conf 0.95)'})).toEqual({ts: 6, who: 'Decision layer', what: 'Detected: TAMPERING (conf 0.95)'});
  });
  it('maps A3 evidence names and byte sizes', () =>
    expect(evidenceView({name: 'messages.jsonl', bytes: 213420, path: 'evidence/inc/messages.jsonl'})).toEqual({title: 'messages.jsonl', file: 'messages.jsonl', size: 213420}));
  it('reads the flat A5 draft fields', () => {
    const d = {sector: 'Health', critical_to_mission: 'Yes: patient monitoring', affected_system: {host_name: 'MON-11', hardware_model: 'demo-monitor', ip_address: null}, symptoms: ['a', 'b']};
    expect(reportValue(d, 'sector')).toBe('Health');
    expect(reportValue(d, 'critical_to_mission')).toBe('Yes: patient monitoring');
    expect(reportValue(d, 'hostname')).toBe('MON-11');
    expect(reportValue(d, 'model')).toBe('demo-monitor');
    expect(reportValue(d, 'ip_address')).toBe('');
    expect(reportValue(d, 'symptoms')).toBe('a\nb');
  });
  it('uses one CERT-In anchor: the report deadline, else 6 h from notice', () => {
    expect(certDeadline(rec({clock_deadline_ts: 99}), rec({detected_ts: 10}))).toBe(99);
    expect(certDeadline(null, rec({detected_ts: 10}, 50))).toBe(10 + 6 * 3600_000);
  });
});
