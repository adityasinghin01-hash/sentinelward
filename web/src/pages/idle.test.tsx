import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import {MemoryRouter, Route, Routes} from 'react-router-dom';
import {WardPage} from './Ward';
import {CensusPage} from './Census';
import {AlertsPage} from './Alerts';
import {LogPage} from './Log';
import {BedPage} from './Bed';
import {SecurityPage} from './Security';
import {BriefingPage} from './Briefing';
import {useWard} from '../lib/store';

beforeEach(() => {
  useWard.setState({beds: [], alerts: [], actions: [], receivedAt: Date.now(), error: null,
    session: {token: 'test', role: 'nurse', name: 'Priya', display_name: 'Priya'}});
});
afterEach(() => {cleanup(); vi.unstubAllGlobals();});

it.each([
  [WardPage, 'No bed data yet'],
  [CensusPage, 'No bed data yet'],
  [AlertsPage, 'No open alerts'],
  [LogPage, 'No actions recorded yet'],
] as const)('gives an idle store-backed screen a readable empty state (%s)', (Page, message) => {
  render(<MemoryRouter><Page /></MemoryRouter>);
  expect(screen.getByText(message)).toBeInTheDocument();
  expect(screen.queryByText(/Loading.*ward/)).not.toBeInTheDocument();
});
it('replaces the ward skeleton after an empty snapshot arrives', () => {
  useWard.setState({receivedAt: null});
  const view = render(<MemoryRouter><WardPage /></MemoryRouter>);
  expect(screen.getByText('Loading ward beds…')).toBeInTheDocument();
  useWard.setState({receivedAt: Date.now()});
  view.rerender(<MemoryRouter><WardPage /></MemoryRouter>);
  expect(screen.getByText('No bed data yet')).toBeInTheDocument();
  expect(screen.queryByText('Loading ward beds…')).not.toBeInTheDocument();
});
it('shows a bed loading state and then a readable unavailable state on an idle ward', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({detail: 'No monitor data yet'}), {status: 404})));
  render(<MemoryRouter initialEntries={['/bed/B03']}><Routes><Route path="/bed/:bedId" element={<BedPage />} /></Routes></MemoryRouter>);
  expect(screen.getByText('Loading bed B03…')).toBeInTheDocument();
  expect(await screen.findByText('Bed B03 not available')).toBeInTheDocument();
  expect(screen.getByRole('link', {name: 'Back to Ward'})).toBeInTheDocument();
});
it('explains empty monitor and incident lists after the security requests complete', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('[]')));
  render(<MemoryRouter><SecurityPage /></MemoryRouter>);
  expect(await screen.findByText('No monitors reported')).toBeInTheDocument();
  expect(await screen.findByText('No open incidents')).toBeInTheDocument();
  expect(screen.getByText('No actions recorded')).toBeInTheDocument();
});
it('explains an absent briefing instead of leaving the reading column blank', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('null')));
  render(<MemoryRouter><BriefingPage /></MemoryRouter>);
  expect(await screen.findByText('No briefing yet')).toBeInTheDocument();
});
