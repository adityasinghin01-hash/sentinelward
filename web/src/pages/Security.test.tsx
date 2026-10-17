import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {SecurityPage} from './Security';
import {useWard} from '../lib/store';
import type {Action} from '../lib/types';

const writes: {url: string; body: unknown}[] = [];
let isolated = false;
beforeEach(() => {
  isolated = false; writes.length = 0;
  useWard.setState({session: {token: 'test', role: 'it', name: 'Sam', display_name: 'Sam'}, beds: [], alerts: [], actions: []});
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    if (init.method && init.method !== 'GET') {writes.push({url, body: JSON.parse(String(init.body))}); return new Response('{}');}
    const data = url === '/api/devices' ? [{device_id: 'MON-01', bed_id: 'B01', isolated, online: true, senders: 2}] :
      url === '/api/ward' ? {beds: []} : url.startsWith('/api/actions') ? {actions: []} : [];
    return new Response(JSON.stringify(data));
  }));
});
afterEach(() => {cleanup(); vi.unstubAllGlobals();});

describe('security monitor controls', () => {
  it('names the device, explains the consequence and isolates only after confirmation', async () => {
    render(<MemoryRouter><SecurityPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', {name: 'Isolate MON-01'}));
    expect(writes).toHaveLength(0);
    expect(screen.getByRole('alertdialog')).toHaveTextContent('MON-01');
    expect(screen.getByRole('button', {name: 'Cancel'})).toHaveFocus();
    fireEvent.click(screen.getByRole('button', {name: 'Isolate monitor'}));
    await waitFor(() => expect(writes[0]).toEqual({url: '/api/devices/MON-01/isolate', body: {type: 'isolate_device', deviceId: 'MON-01', bedId: 'B01'}}));
  });
  it('reconnects using the original reversible action, only after confirmation', async () => {
    isolated = true;
    const a: Action = {id: 'act_1', actor: 'A2', action_code: 'disable_client', action: 'Cut off MON-01', occurred_at: 1, bed_id: 'B01', device_id: 'MON-01', mode: 'automatic', undoable: true, approved_by: null, references_action_id: null};
    useWard.setState({actions: [a]});
    render(<MemoryRouter><SecurityPage /></MemoryRouter>);
    fireEvent.click((await screen.findAllByRole('button', {name: 'Undo'}))[0]);
    expect(writes).toHaveLength(0);
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Reconnect this monitor?');
    fireEvent.click(screen.getByRole('button', {name: 'Reconnect monitor'}));
    await waitFor(() => expect(writes[0]).toEqual({url: '/api/actions/act_1/undo', body: {type: 'undo_action', originalActionId: 'act_1', bedId: 'B01'}}));
  });
});
