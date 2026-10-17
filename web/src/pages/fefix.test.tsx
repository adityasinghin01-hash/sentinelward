import {afterEach, beforeEach, expect, it} from 'vitest';
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {WardPage} from './Ward';
import {CensusPage} from './Census';
import {useWard} from '../lib/store';
import type {Bed} from '../lib/types';

const now = Date.now();
function bed(id: string, verdict: Bed['verdict']): Bed {
  return {bed_id:id, device_id:`MON-${id.slice(1)}`, verdict, priority:verdict==='BOTH'?'high':'none',
    isolated:false, connected:true, is_trusted:verdict==='NORMAL', display:verdict==='NORMAL'?'live':'last_trusted',
    last_updated_at:now, trust_score:100, vitals:{hr:190,spo2:80,systolic:80,diastolic:40},
    waveform:{ecg:[],ppg:[]}, last_trusted:{captured_at:now-120_000,vitals:{hr:74,spo2:97,systolic:123,diastolic:81},waveform:{ecg:[],ppg:[]}},
    chip_opinion:null, last_bedside_check:null, reason:'', requested_action:'Check patient at bedside', acknowledged:false,
    offline_since:null, manual:null, assignment:null, nurse_call:null};
}
beforeEach(() => useWard.setState({beds:[bed('B01','NORMAL'),bed('B02','TAMPERING'),bed('B03','BOTH')],alerts:[],actions:[],error:'',hidden:true}));
afterEach(cleanup);
it('security filtering includes combined emergencies and removes other bed links from keyboard navigation', () => {
  render(<MemoryRouter><WardPage /></MemoryRouter>);
  const security = screen.getByRole('button', {name:/Security concern/});
  expect(security).toHaveTextContent('2');
  fireEvent.click(security);
  expect(screen.queryByRole('link',{name:/B01:/})).toBeNull();
  expect(screen.getAllByRole('link',{name:/Open bed/})).toHaveLength(2);
  fireEvent.click(screen.getByRole('button',{name:/Emergency/}));
  expect(screen.getAllByRole('link',{name:/Open bed/})).toHaveLength(1);
  expect(screen.getByRole('link',{name:/B03:/})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/All beds/}));
  expect(screen.getAllByRole('link',{name:/Open bed/})).toHaveLength(3);
});
it('Census puts the frozen recording age beside trusted values and uses shared verdict chips', () => {
  render(<MemoryRouter><CensusPage /></MemoryRouter>);
  const row = screen.getByRole('row',{name:/B02/});
  expect(within(row).getByText(/Last trusted · 2 min ago/)).toBeInTheDocument();
  expect(within(row).getByText('74')).toBeInTheDocument();
  expect(row.querySelector('[data-state="TAMPERING"]')).not.toBeNull();
});

it('keeps a tampering bed in the security filter when a high alert raises its display group', () => {
  useWard.setState({alerts:[{alert_id:'a',bed_id:'B02',verdict:'EMERGENCY',priority:'high',ts:now,text:'Emergency',to:[],ladder_step:1,status:'open',acked_by:null,acked_ts:null}]});
  render(<MemoryRouter><WardPage /></MemoryRouter>);
  const security = screen.getByRole('button', {name:/Security concern/});
  expect(security).toHaveTextContent('2');
  fireEvent.click(security);
  expect(screen.getByRole('link',{name:/B02:/})).toBeInTheDocument();
  expect(screen.getByRole('link',{name:/B03:/})).toBeInTheDocument();
});
