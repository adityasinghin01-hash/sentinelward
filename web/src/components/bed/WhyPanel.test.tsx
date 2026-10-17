import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, expect, it} from 'vitest';
import type {BedDetail} from '../../lib/types';
import {WhyPanel} from './WhyPanel';
afterEach(cleanup);
it('keeps available checks visible and unavailable checks and chip evidence in disclosures', () => {
  const detail = {verdict:'TAMPERING', reason:'Old sequence received', connected:true, isolated:false, display:'live', trust_score:10, requested_action:'Check patient at bedside', chip_opinion:null, recent_verdicts:[],scores:{M4:{score:.98,reason:'Old sequence received',extra:{}},M2:{score:null,reason:'No monitor alarm in this window',extra:{}}}} as unknown as BedDetail;
  render(<WhyPanel detail={detail} now={Date.now()} />);
  expect(screen.getByRole('heading',{name:'Why SentinelWard says this'})).toBeInTheDocument();
  expect(screen.getAllByText('Replay check')[0].closest('details')).toBeNull();
  expect(screen.getAllByText('Real emergency')[0].closest('details')).not.toHaveAttribute('open');
  expect(screen.getByRole('region',{name:'AI-chip second opinion'}).closest('details')).not.toHaveAttribute('open');
  expect(screen.getByText('Checking')).toBeInTheDocument();
});
