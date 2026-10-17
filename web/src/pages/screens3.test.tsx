import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {render, screen, cleanup} from '@testing-library/react';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import type {ReactElement} from 'react';
import {useWard} from '../lib/store';
import type {Action, Alert, Role} from '../lib/types';
import {AlertsPage} from './Alerts';
import {ReportPage} from './Report';
import {IncidentPage} from './Incident';
import {LogPage} from './Log';
import {BriefingPage, nursesOnly} from './Briefing';

function mockFetch(gets: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const key = Object.keys(gets).sort((a, b) => b.length - a.length).find(k => url.startsWith(k));
    return key ? new Response(JSON.stringify(gets[key])) : new Response(JSON.stringify({detail: 'no'}), {status: 404});
  }));
}
function as(role: Role) { useWard.setState({session: {token: 't', role, name: role, display_name: role}}); }
function at(path: string, route: string, el: ReactElement) {
  return render(<MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={el} /></Routes></MemoryRouter>);
}
const rec = (record_id: string, kind: string, data: Record<string, unknown>, ts = Date.now() - 60_000) =>
  ({record_id, kind, ts, by: kind === 'report' ? 'A5' : 'A3', version: 2, data, updated_ts: null, updated_by: null});
const incident = rec('inc_1', 'incident', {
  incident_id: 'inc_1', bed_id: 'B11', device_id: 'MON-11', status: 'open', verdict: 'TAMPERING', attack_start_ts: 2000, detected_ts: 3000,
  evidence: [{name: 'messages.jsonl', bytes: 213420, sha256: 'a'.repeat(64), captured_at: 3100, path: 'evidence/inc_1/messages.jsonl'}],
  timeline: [{ts: 1000, event: 'A1 send_message: Alert al_1 (UNSURE, medium) step 1 -> staff:tom'},
             {ts: 3000, event: 'Detected: TAMPERING (conf 0.95)'},
             {ts: 3200, event: 'A2 disable_client: Cut off MON-11 at the hub after TAMPERING'}],
});
const report = rec('rp_1', 'report', {
  report_id: 'rp_1', incident_id: 'inc_1', status: 'draft', sector: 'Health', critical_to_mission: 'Yes: patient monitoring',
  affected_system: {device_id: 'MON-11', hardware_model: 'demo-monitor', host_name: 'MON-11', ip_address: null},
  physical_location: 'Ward 4B (demo), bed B11', clock_deadline_ts: Date.now() + 3600_000,
  evidence: [{name: 'messages.jsonl', sha256: 'a'.repeat(64)}],
});

beforeEach(() => mockFetch({'/api/incidents/inc_1': incident, '/api/incidents': [incident], '/api/reports': [report]}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('S8 CERT-In draft (#4)', () => {
  it('fills sector, critical-to-mission and host name from the A5 draft', async () => {
    as('it');
    at('/incident/inc_1/report', '/incident/:incidentId/report', <ReportPage />);
    expect(await screen.findByDisplayValue('Health')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Yes: patient monitoring')).toBeInTheDocument();
    expect(screen.getAllByDisplayValue('MON-11').length).toBeGreaterThan(0);
    expect(screen.getByDisplayValue('demo-monitor')).toBeInTheDocument();
  });
});

describe('S7 incident (#8)', () => {
  it('shows the A3 timeline text and agent, and named evidence with its size', async () => {
    as('it'); useWard.setState({actions: []});
    at('/incident/inc_1', '/incident/:incidentId', <IncidentPage />);
    expect(await screen.findByText('Cut off MON-11 at the hub')).toBeInTheDocument();
    expect(screen.getByText('Detected possible monitor tampering')).toBeInTheDocument();
    expect(screen.getByText(/Attack starts/)).toBeInTheDocument();
    expect(screen.getByText('Signal record')).toBeInTheDocument();
    expect(screen.getByText(/208\.4 KB/)).toBeInTheDocument();
    expect(screen.queryByText('Event')).toBeNull();
  });
});

describe('S4 acknowledged count (#10)', () => {
  it('does not count auto-closed alerts as acknowledged', () => {
    as('nurse');
    const base: Omit<Alert, 'alert_id' | 'status' | 'acked_by'> = {ts: Date.now(), bed_id: 'B07', verdict: 'UNSURE', priority: 'medium', text: 't', to: [], ladder_step: 1, acked_ts: null};
    useWard.setState({alerts: [
      {...base, alert_id: 'a', status: 'open', acked_by: null},
      {...base, alert_id: 'b', status: 'acked', acked_by: 'staff:priya'},
      {...base, alert_id: 'c', status: 'closed', acked_by: null},
      {...base, alert_id: 'd', status: 'closed', acked_by: null},
    ]});
    at('/alerts', '/alerts', <AlertsPage />);
    expect(screen.getByRole('radio', {name: /^Acknowledged/})).toHaveTextContent('1');
    expect(screen.getByRole('radio', {name: /^Auto-closed/})).toHaveTextContent('2');
  });
});

describe('S11 undo (#13)', () => {
  it('shows Undo only on rows the API marks undoable', () => {
    as('it');
    const a = (id: string, undoable: boolean): Action => ({id, occurred_at: Date.now(), actor: 'A1', action_code: 'x', action: id, bed_id: 'B01', device_id: null, approved_by: null, mode: 'automatic', undoable, references_action_id: null});
    useWard.setState({actions: [a('cut-off', true), a('message', false), a('briefing', false)]});
    at('/log', '/log', <LogPage />);
    expect(screen.getAllByRole('button', {name: /Undo/})).toHaveLength(1);
  });
});

describe('S10 workload (#13) and briefing (#11)', () => {
  it('lists nurses only', () => {
    expect(nursesOnly([
      {nurse_id: 'staff:dr_mehta', nurse_name: 'Dr Mehta (Doctor)', alarms_last_2h: 3},
      {nurse_id: 'staff:priya', nurse_name: 'Priya (Nurse)', alarms_last_2h: 16},
      {nurse_id: 'staff:x', nurse_name: 'X', role: 'doctor', alarms_last_2h: 1},
      {nurse_id: 'staff:tom', nurse_name: 'Tom (Nurse)', role: 'nurse', alarms_last_2h: 18},
    ]).map(n => n.nurse_id)).toEqual(['staff:priya', 'staff:tom']);
  });
  it('draws blind time from the same facts the summary was written from', async () => {
    as('nurse');
    mockFetch({'/api/briefing': {since: '2026-10-17T13:30:16.918Z', generated_by: 'template', summary: 'Blind time: B03 15.4 min.', incidents: 0, untrusted_beds: 7, open_tickets: 2,
      blind_time: [{bed_id: 'B09', minutes: 0.07}], record_id: 'br', ts: Date.now(), fallback_reason: 'Granite unavailable (ReadTimeout)',
      facts: {shift_start: '08:00', data_from: '18:41', incident_count: 6, untrusted_bed_count: 5, open_ticket_count: 2, blind_time: [{bed_id: 'B03', minutes: 15.4}]}}});
    at('/briefing', '/briefing', <BriefingPage />);
    expect(await screen.findByText('15.4 min')).toBeInTheDocument();
    expect(screen.queryByText('0.1 min')).toBeNull();
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText(/Template used because: Granite unavailable/)).toBeInTheDocument();
  });
});
