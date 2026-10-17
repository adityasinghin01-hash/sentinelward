import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import {ReportPage} from './Report';
import {useWard} from '../lib/store';

afterEach(() => {cleanup(); vi.unstubAllGlobals();});
describe('report draft presentation preserves the source data', () => {
  it('saves an untouched raw action field unchanged when a person edits a different field', async () => {
    const raw = '02:20:05 A2 disable_client: Cut off MON-10 at the hub after TAMPERING (conf 0.98); session wiped';
    const writes: {url: string; body: any}[] = [];
    useWard.setState({session: {token: 'test', role: 'it', name: 'Sam', display_name: 'Sam'}});
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      if (init.method && init.method !== 'GET') {writes.push({url, body: JSON.parse(String(init.body))}); return new Response('{}');}
      const data = url === '/api/reports' ? [{record_id: 'rp_private', kind: 'report', by: 'A5', ts: Date.now(), version: 1, data: {
        incident_id: 'inc_private', bed_id: 'B10', device_id: 'MON-10', status: 'draft', fields: {actions_taken: {value: raw, status: 'observed', source: 'incident'}},
      }}] : url === '/api/ward' ? {beds: [], received_at: Date.now()} : url.startsWith('/api/actions') ? {actions: []} : [];
      return new Response(JSON.stringify(data));
    }));
    render(<MemoryRouter initialEntries={['/incident/inc_private/report']}><Routes><Route path="/incident/:incidentId/report" element={<ReportPage />} /></Routes></MemoryRouter>);
    const actions = await screen.findByLabelText('Actions taken');
    expect(actions).toHaveValue('02:20:05 Network agent: Cut off MON-10 at the hub. Monitor may be hacked.');
    fireEvent.focus(screen.getByLabelText('Reporter name'));
    fireEvent.change(screen.getByLabelText('Reporter name'), {target: {value: 'Anita'}});
    fireEvent.blur(screen.getByLabelText('Reporter name'));
    fireEvent.click(screen.getByRole('button', {name: 'Save draft'}));
    await waitFor(() => expect(writes[0]?.url).toBe('/api/reports/rp_private'));
    expect(writes[0].body.report.fields.actions_taken).toEqual({value: raw, status: 'observed', source: 'incident'});
    expect(writes[0].body.report.fields.reporter_name.value).toBe('Anita');
  });
});
