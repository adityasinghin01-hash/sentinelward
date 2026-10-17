import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import type {Action} from '../../lib/types';
import {useWard} from '../../lib/store';
import {BedActions} from './BedActions';
const action: Action = {id:'act_123', occurred_at:Date.now(), actor:'A2', action_code:'disable_client', action:'Cut off MON-05 at the hub after TAMPERING (conf 0.98, held 20 s); session wiped', bed_id:'B05', device_id:'MON-05', approved_by:null, mode:'automatic', undoable:true, references_action_id:null};
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
it('explains who acted and why while keeping the audit record in Details', () => {
  render(<BedActions actions={[action, {...action,id:'act_124',actor:'A3',action_code:'hash_file',undoable:false,action:`inc_abc/messages.jsonl: 200 bytes, sha256 ${'a'.repeat(64)}`}]} />);
  expect(screen.getByText('B05 · Cut off MON-05 at the hub')).toBeInTheDocument();
  expect(screen.getByText(/Network agent/)).toBeInTheDocument();
  expect(screen.getByText('Monitor may be hacked')).toBeInTheDocument();
  const raw = screen.getByText(/inc_abc\/messages.jsonl/);
  expect(raw.closest('details')).not.toHaveAttribute('open');
  expect(screen.getByText('B05 · Fingerprinted the signal record')).toBeInTheDocument();
});
it('requires confirmation before the existing undo write and focuses Cancel', async () => {
  useWard.setState({session:{role:'it',name:'it',display_name:'IT',token:'t'}});
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({command_id:'c',accepted_at:1}),{status:202}));
  vi.stubGlobal('fetch', fetch);
  render(<BedActions actions={[action]} />);
  fireEvent.click(screen.getByRole('button',{name:'Undo'}));
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getByRole('button',{name:'Cancel'})).toHaveFocus();
  fireEvent.click(screen.getByRole('button',{name:'Reconnect monitor'}));
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(fetch.mock.calls[0]).toEqual(['/api/actions/act_123/undo', expect.objectContaining({method:'POST',body:JSON.stringify({type:'undo_action',originalActionId:'act_123',bedId:'B05'})})]);
});
