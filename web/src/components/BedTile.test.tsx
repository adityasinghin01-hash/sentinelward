import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, expect, it} from 'vitest';
import {MemoryRouter} from 'react-router-dom';
import type {Alert, Bed} from '../lib/types';
import {BedTile} from './BedTile';
afterEach(cleanup);
const bed: Bed = {chip_opinion: null, priority: 'medium', trust_score: 0, reason: '', requested_action: '', acknowledged: false, offline_since: null, manual: null, last_bedside_check: null, assignment: null, nurse_call: null, bed_id: 'B10', device_id: 'MON-10', verdict: 'TAMPERING', isolated: true,
  is_trusted: false, connected: true, display: 'last_trusted', last_updated_at: 1000, last_trusted: null,
  waveform: {ecg: [], ppg: []}, vitals: {hr: 56, spo2: 100, systolic: null, diastolic: null}};
it('shows the flagged reason exactly once in a rendered tile', () => {
  render(<MemoryRouter><BedTile bed={bed} now={4000} /></MemoryRouter>);
  expect(screen.getAllByText('Data untrusted · device flagged')).toHaveLength(1);
});
it('omits the BP slot when no blood pressure is supplied', () => {
  render(<MemoryRouter><BedTile bed={bed} now={4000} /></MemoryRouter>);
  expect(screen.queryByText('BP')).not.toBeInTheDocument();
  expect(screen.queryByText('/')).not.toBeInTheDocument();
});
it('keeps pressure numbers when either current or last-trusted pressure exists', () => {
  render(<MemoryRouter><BedTile bed={{...bed, vitals: {...bed.vitals!, systolic: 120, diastolic: 80}}} now={4000} /></MemoryRouter>);
  expect(screen.getByText('120', {exact: false})).toBeInTheDocument();
});
it('holds the BP slot for a previously supplied channel even when its latest reading is missing', () => {
  render(<MemoryRouter><BedTile bed={{...bed, last_trusted: {captured_at: 1000, waveform: bed.waveform, vitals: {...bed.vitals!, systolic: 122, diastolic: 79}}}} now={4000} /></MemoryRouter>);
  expect(screen.queryByText('Not supplied')).not.toBeInTheDocument();
  expect(screen.getByText('122', {exact: false})).toBeInTheDocument();
});
it('shows a calm first-reading state without implying that the bed is unoccupied', () => {
  const {container} = render(<MemoryRouter><BedTile bed={{...bed, verdict: null, isolated: false, display: 'empty', last_updated_at: null, vitals: null}} now={4000} /></MemoryRouter>);
  expect(screen.getByText('No monitor data yet')).toBeInTheDocument();
  expect(screen.getByText('Waiting for the first reading')).toBeInTheDocument();
  expect(screen.queryByLabelText('Vital signs')).not.toBeInTheDocument();
  expect(container.querySelector('.is-untrusted')).toBeNull();
  expect(container.textContent).not.toMatch(/not admitted|unoccupied/i);
});
it('keeps flagged-device evidence visible even before the first trusted reading', () => {
  const {container} = render(<MemoryRouter><BedTile bed={{...bed, display: 'empty', last_updated_at: null}} now={4000} /></MemoryRouter>);
  expect(screen.getByText('Data untrusted · device flagged')).toBeInTheDocument();
  expect(screen.getByLabelText('Vital signs')).toBeInTheDocument();
  expect(container.querySelector('.is-awaiting')).toBeNull();
});
it('keeps an open emergency alert urgent even when the monitor has sent no data', () => {
  const alert = {alert_id: 'alert', bed_id: bed.bed_id, priority: 'high', verdict: 'EMERGENCY', status: 'open', ladder_step: 2, ts: 1000} as Alert;
  const {container} = render(<MemoryRouter><BedTile bed={{...bed, verdict: null, isolated: false, display: 'empty', last_updated_at: null}} alerts={[alert]} now={4000} /></MemoryRouter>);
  expect(screen.getByText('Go now · see alert')).toBeInTheDocument();
  expect(container.querySelector('.tone-emergency')).not.toBeNull();
  expect(container.querySelector('.is-awaiting')).toBeNull();
});
