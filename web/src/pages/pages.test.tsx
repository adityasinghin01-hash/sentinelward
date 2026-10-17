import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {render, screen, fireEvent, waitFor, cleanup} from '@testing-library/react';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import type {ReactElement} from 'react';
import {useWard} from '../lib/store';
import type {Alert, Role} from '../lib/types';
import {AlertsPage} from './Alerts';
import {DemoPage} from './Demo';
import {TicketsPage} from './Tickets';
import {ReportPage} from './Report';
import {can, ticketColumn, bedState} from '../lib/domain';

// Mocked API only (tests never reach a server). Records every write.
let writes: {method: string; url: string; body: unknown}[] = [];
function mockFetch(gets: Record<string, unknown>) {
  writes = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    if (method !== 'GET') { writes.push({method, url, body: JSON.parse(String(init.body ?? '{}'))}); return new Response(JSON.stringify({command_id: 'c', accepted_at: 1}), {status: 202}); }
    const key = Object.keys(gets).find(k => url.startsWith(k));
    return key ? new Response(JSON.stringify(gets[key])) : new Response(JSON.stringify({detail: 'no'}), {status: 404});
  }));
}
function as(role: Role) { useWard.setState({session: {token: 't', role, name: role, display_name: role}}); }
function at(path: string, route: string, el: ReactElement) {
  return render(<MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={el} /></Routes></MemoryRouter>);
}
const alert: Alert = {alert_id: 'al_1', ts: Date.now() - 5000, bed_id: 'B05', verdict: 'EMERGENCY', priority: 'high', text: 'Bed 5 — go now', to: ['staff:priya'], ladder_step: 1, status: 'open', acked_by: null, acked_ts: null};

beforeEach(() => mockFetch({'/api/ward': {beds: [], received_at: 1}, '/api/alerts': [alert], '/api/actions': {actions: []}}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('S4 alerts', () => {
  it('acknowledges the selected alert through the alert route', async () => {
    as('nurse'); useWard.setState({alerts: [alert]});
    at('/alerts', '/alerts', <AlertsPage />);
    fireEvent.click(screen.getByText('Bed 5 — go now'));
    fireEvent.click(screen.getByRole('button', {name: 'Acknowledge'}));
    await waitFor(() => expect(writes[0]).toMatchObject({method: 'POST', url: '/api/alerts/al_1/ack'}));
  });
  it('does not let IT acknowledge clinical alerts', () => {
    as('it'); useWard.setState({alerts: [alert]});
    at('/alerts', '/alerts', <AlertsPage />);
    fireEvent.click(screen.getByText('Bed 5 — go now'));
    expect(screen.getByRole('button', {name: 'Acknowledge'})).toBeDisabled();
  });
});

describe('S12 demo', () => {
  it('runs the chosen scenario and speed, and resets only after confirming', async () => {
    as('operator'); mockFetch({'/api/health': {ok: true, mqtt_connected: true, beds_online: 0, last_message_ts: null, invalid_messages: 0}});
    at('/demo', '/demo', <DemoPage />);
    fireEvent.click(screen.getByLabelText(/Replay attack/));
    fireEvent.click(screen.getByRole('button', {name: '5×'}));
    fireEvent.click(screen.getByRole('button', {name: /Run/}));
    await waitFor(() => expect(writes[0]).toMatchObject({url: '/api/demo/run', body: {scenario: 'replay_attack', speed: 5}}));
    fireEvent.click(screen.getByRole('button', {name: /Reset ward/}));
    expect(writes).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', {name: 'Yes, reset'}));
    await waitFor(() => expect(writes[1]).toMatchObject({url: '/api/demo/reset'}));
  });
});

describe('S9 tickets', () => {
  it('starts a new ticket with PATCH status assigned', async () => {
    as('biomedical');
    mockFetch({'/api/tickets': [{record_id: 'tk_1', kind: 'ticket', ts: 1, by: 'A6', version: 1, updated_ts: null, updated_by: null,
      data: {device_id: 'MON-04', bed_id: 'B04', status: 'new', fault_types: ['LOOSE_SENSOR'], issues_30d: 3, suggestion: 'Refit'}}]});
    at('/tickets', '/tickets', <TicketsPage />);
    fireEvent.click(await screen.findByRole('button', {name: /Start/}));
    await waitFor(() => expect(writes[0]).toMatchObject({method: 'PATCH', url: '/api/tickets/tk_1', body: {status: 'assigned'}}));
    expect(screen.getByText('MON-04', {selector: '.plain-list span'})).toBeInTheDocument();
  });
});

describe('S8 report', () => {
  it('keeps "Mark as sent" disabled and says why until the checklist is complete', async () => {
    as('it');
    mockFetch({'/api/reports': [{record_id: 'rep_1', kind: 'report', ts: Date.now(), by: 'A5', version: 1, updated_ts: null, updated_by: null,
      data: {incident_id: 'inc_1', status: 'needs_review', deadline_ts: Date.now() + 3600_000, fields: {}, evidence: [], checklist: {}}}]});
    at('/incident/inc_1/report', '/incident/:incidentId/report', <ReportPage />);
    const send = await screen.findByRole('button', {name: /Mark as sent by me/});
    expect(send).toBeDisabled();
    expect(screen.getByText(/To mark as sent: tick “Facts checked”/)).toBeInTheDocument();
  });
});

describe('domain rules', () => {
  it('mirrors backend write roles', () => {
    expect(can('nurse', 'clinical')).toBe(true); expect(can('operator', 'clinical')).toBe(false);
    expect(can('it', 'security')).toBe(true); expect(can('doctor', 'security')).toBe(false);
    expect(can('biomedical', 'ticketEdit')).toBe(true); expect(can('it', 'demo')).toBe(false);
  });
  it('maps ticket statuses to the three board columns', () => {
    expect(ticketColumn('new')).toBe('new'); expect(ticketColumn('open')).toBe('new');
    expect(ticketColumn('assigned')).toBe('progress'); expect(ticketColumn('resolved')).toBe('done'); expect(ticketColumn('done')).toBe('done');
  });
  it('labels a bed with no monitor instead of inventing a verdict', () => {
    const s = bedState({bed_id: 'B04', verdict: null, priority: 'none', is_trusted: false, connected: false, display: 'empty', last_updated_at: null} as never);
    expect(s.label).toBe('NO MONITOR'); expect(s.offline).toBe(true);
  });
});
