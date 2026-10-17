import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import {BedPage} from '../../pages/Bed';
import {useWard} from '../../lib/store';
import type {BedDetail} from '../../lib/types';

const now = Date.now();
const detail: BedDetail = {
  bed_id:'B05',device_id:'MON-05',verdict:'TAMPERING',priority:'medium',trust_score:0,is_trusted:false,
  connected:true,isolated:true,reason:'Old sequence received',requested_action:'Check patient at bedside',acknowledged:false,
  last_updated_at:now,vitals:{hr:190,spo2:82,systolic:80,diastolic:40},waveform:{ecg:[99,99],ppg:[99,99]},
  last_trusted:{captured_at:now-60_000,vitals:{hr:74,spo2:97,systolic:123,diastolic:81},waveform:{ecg:[0,1,0],ppg:[0,.5,0]}},
  display:'last_trusted',offline_since:null,manual:null,last_bedside_check:null,assignment:null,nurse_call:null,chip_opinion:null,
  scores:{},recent_verdicts:[],open_alerts:[],device:{online:true,isolated:true,isolated_since:now-30_000,last_seen_ts:now},
};
let writes: {url: string; body: unknown}[];
function open() { render(<MemoryRouter initialEntries={['/bed/B05']}><Routes><Route path="/bed/:bedId" element={<BedPage />} /></Routes></MemoryRouter>); }
beforeEach(() => {
  writes=[];
  useWard.setState({session:{role:'nurse',token:'t',name:'nurse',display_name:'Nurse'},beds:[],actions:[],alerts:[]});
  sessionStorage.clear();
  vi.stubGlobal('fetch',vi.fn(async (url: string, init: RequestInit={}) => {
    if (init.method === 'POST') { writes.push({url,body:JSON.parse(String(init.body))}); return new Response(JSON.stringify({command_id:'c',accepted_at:now}),{status:202}); }
    return new Response(JSON.stringify(url.includes('/history') ? {points:[{ts:now,hr:190,spo2:82,sys:80,dia:40,rr:22,trusted:false,verdict:'TAMPERING'}]} : detail));
  }));
});
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
it('keeps last-trusted values separate from incoming readings and freezes both traces', async () => {
  open();
  await screen.findByRole('heading',{name:'Last trusted signals'});
  const vitals = screen.getByRole('group',{name:'Vital signs'});
  expect(within(vitals).getByText('74')).toBeInTheDocument();
  expect(within(vitals).queryByText('190')).not.toBeInTheDocument();
  expect(screen.getByText(/HR 190 · SpO₂ 82 · BP 80\/40/)).toBeInTheDocument();
  expect(screen.getAllByRole('img',{name:/Last trusted recording, held still/})).toHaveLength(2);
  expect(writes).toEqual([]);
});
it('labels received values as untrusted when no trusted snapshot exists', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(
    url.includes('/history') ? {points: []} : {...detail, last_trusted: null}
  ))));
  open();
  await screen.findByRole('heading', {name: 'Last values received · not trusted'});
  expect(within(screen.getByRole('group', {name: 'Vital signs'})).getByText('190')).toBeInTheDocument();
  expect(screen.getByText('Not trusted · showing the last values received; no trusted recording is available. Check by hand.')).toBeInTheDocument();
  expect(screen.queryByText(/Frozen at the newest trusted recording|showing the last good recording/)).not.toBeInTheDocument();
  expect(screen.queryByRole('img', {name: /Last trusted recording/})).not.toBeInTheDocument();
});
it('explains a monitor that has never sent data without claiming there are frozen readings', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(
    url.includes('/history') ? {points: []} : {...detail, verdict: null, isolated: false,
      display: 'empty', last_updated_at: null, last_trusted: null, vitals: null, waveform: {ecg: [], ppg: []}}
  ))));
  open();
  await screen.findByRole('heading', {name: 'No monitor data yet'});
  expect(screen.getByRole('heading', {name: 'Waiting for the first reading'})).toBeInTheDocument();
  expect(screen.queryByRole('group', {name: 'Vital signs'})).not.toBeInTheDocument();
  expect(screen.queryByText(/showing the last values received/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Patient OK'})).toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Patient NOT OK'})).toBeInTheDocument();
});
it.each(['Patient OK','Patient NOT OK'])('preserves the %s request', async label => {
  open();
  fireEvent.click(await screen.findByRole('button',{name:label}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual({url:'/api/beds/B05/bedside-check',body:{type:'confirm_bedside',bedId:'B05',status:label==='Patient OK'?'patient_ok':'patient_not_ok'}});
});
it('saves manual readings to the same endpoint and clears the form only after success', async () => {
  open();
  const save = await screen.findByRole('button',{name:'Record hand check'});
  const form = save.closest('form')!;
  const fields = within(form).getAllByRole('textbox');
  fireEvent.change(fields[0],{target:{value:'72'}});
  fireEvent.change(fields[1],{target:{value:'98'}});
  fireEvent.change(fields[2],{target:{value:'Portable oximeter'}});
  fireEvent.click(save);
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual({url:'/api/beds/B05/manual-reading',body:{type:'record_manual_reading',bedId:'B05',notes:'Portable oximeter',heartRate:72,spo2:98}});
  await waitFor(() => expect(fields[0]).toHaveValue(''));
});

it('shows a flagged device without claiming a cut-off when no action confirms it', async () => {
  open();
  await screen.findByRole('heading', {name: 'Last trusted signals'});
  const link = screen.getByText('Device link').closest('div')!;
  expect(within(link).getByText('Data untrusted · device flagged')).toBeInTheDocument();
  expect(screen.queryByText(/cut off by IT|monitor cut off/i)).not.toBeInTheDocument();
});
it('keeps a confirmed B05 hub cut-off visible in the action history', async () => {
  useWard.setState({actions: [{id: 'cut-b05', occurred_at: now, actor: 'A2', action_code: 'disable_client',
    action: 'Cut off MON-05 at the hub after TAMPERING; session wiped', bed_id: 'B05', device_id: 'MON-05',
    approved_by: null, mode: 'automatic', undoable: true, references_action_id: null}]});
  open();
  expect(await screen.findByText('B05 · Cut off MON-05 at the hub')).toBeInTheDocument();
  expect(screen.getByText('Cut off by IT', {exact: true})).toBeInTheDocument();
});

it('puts bedside confirmation and the directive before signal evidence', async () => {
  open();
  const bedside = await screen.findByRole('heading', {name: 'Bedside check'});
  const signals = screen.getByRole('heading', {name: 'Last trusted signals'});
  const directive = screen.getByRole('heading', {name: 'What to do now'});
  expect(bedside.compareDocumentPosition(signals) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(directive.compareDocumentPosition(signals) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const why = screen.getByRole('heading', {name: 'Why SentinelWard says this'}).closest('.panel')!;
  expect(directive.closest('.panel')!.nextElementSibling).toBe(why);
  expect(why.parentElement).toHaveClass('bed-side');
});
