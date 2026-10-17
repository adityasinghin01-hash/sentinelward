import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it} from 'vitest';
import {MemoryRouter} from 'react-router-dom';
import {ChipOpinionPanel} from './ChipOpinion';
import {BedTile} from './BedTile';
import type {Bed, ChipOpinion} from '../lib/types';

const now = 1792252800000;
const opinion: ChipOpinion = {
  v: 1, bed_id: 'B03', ts: now, alarm_code: 'VTACH', p_real: .87, label: 'real',
  threshold: .5, model: 'M2-cnn-nnpa-2026-10-17', device: 'nnpa:0', latency_ms: 1.3,
  heldout_challenge_cinc: .623, heldout_challenge_vtac: .665,
};
afterEach(cleanup);

describe('AI-chip second opinion', () => {
  it('shows live chip evidence and its lower held-out score with plain explainers', () => {
    render(<ChipOpinionPanel opinion={opinion} now={now} />);
    expect(screen.getByRole('heading', {name: 'AI-chip second opinion (IBM Telum II, on-chip)'})).toBeInTheDocument();
    for (const text of ['VTACH', '87%', 'real', 'nnpa:0', '1.3 ms']) expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.getByText('Shown only, not used in decisions. Held-out score 0.623 (CinC) vs live model 0.862.')).toBeInTheDocument();
    expect(screen.getAllByRole('tooltip').length).toBeGreaterThanOrEqual(7);
    expect(screen.getByText(/VTaC held-out score 0.665/)).toBeInTheDocument();
  });

  it('reads the model evaluation values from each message', () => {
    render(<ChipOpinionPanel opinion={{...opinion, p_real: .2, label: 'false', heldout_challenge_cinc: .601, heldout_challenge_vtac: .645}} now={now} />);
    expect(screen.getByText('20%')).toBeInTheDocument();
    expect(screen.getByText('false')).toBeInTheDocument();
    expect(screen.getByText(/Held-out score 0.601/)).toBeInTheDocument();
    expect(screen.getByText(/VTaC held-out score 0.645/)).toBeInTheDocument();
  });

  it.each([null, undefined])('shows the empty state for no opinion (%s)', value => {
    render(<ChipOpinionPanel opinion={value} now={now} />);
    expect(screen.getByText('No alarm judged on the chip yet.')).toBeInTheDocument();
    expect(screen.queryByText('87%')).not.toBeInTheDocument();
  });

  it('clears an opinion at 120 seconds even if no more updates arrive', () => {
    const view = render(<ChipOpinionPanel opinion={opinion} now={now + 119999} />);
    expect(screen.getByText('87%')).toBeInTheDocument();
    view.rerender(<ChipOpinionPanel opinion={opinion} now={now + 120000} />);
    expect(screen.getByText('No alarm judged on the chip yet.')).toBeInTheDocument();
    expect(screen.queryByText('87%')).not.toBeInTheDocument();
  });

  it('shows a ward chip icon only while the opinion is fresh', () => {
    const bed: Bed = {bed_id: 'B03', device_id: 'MON-03', verdict: null, priority: 'none',
      trust_score: 0, is_trusted: false, connected: false, isolated: false, reason: 'No monitor connected yet',
      requested_action: 'None', acknowledged: false, last_updated_at: null, vitals: null,
      waveform: {ecg: [], ppg: []}, last_trusted: null, display: 'empty', offline_since: null,
      manual: null, last_bedside_check: null, assignment: null, nurse_call: null, chip_opinion: opinion};
    const view = render(<MemoryRouter><BedTile bed={bed} now={now} /></MemoryRouter>);
    expect(screen.getByLabelText('AI-chip second opinion available')).toBeInTheDocument();
    view.rerender(<MemoryRouter><BedTile bed={bed} now={now + 120000} /></MemoryRouter>);
    expect(screen.queryByLabelText('AI-chip second opinion available')).not.toBeInTheDocument();
    view.rerender(<MemoryRouter><BedTile bed={{...bed, chip_opinion: null}} now={now} /></MemoryRouter>);
    expect(screen.queryByLabelText('AI-chip second opinion available')).not.toBeInTheDocument();
  });
});
