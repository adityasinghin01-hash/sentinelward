import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import {LogPage} from './Log';
import {useWard} from '../lib/store';
import type {Action} from '../lib/types';

const a = (id: string, actor: string, action_code: string, action: string, mode: Action['mode']): Action => ({id, actor, action_code, action, occurred_at: 1792270180026, bed_id: 'B06', device_id: 'MON-06', mode, undoable: false, approved_by: null, references_action_id: null});
beforeEach(() => useWard.setState({receivedAt: Date.now(), error: null, actions: [
  a('act_secret', 'A2', 'disable_client', 'Cut off MON-06 at the hub after TAMPERING (conf 0.98); session wiped', 'automatic'),
  a('act_staff', 'staff:priya', 'acknowledge_alert', 'Acknowledged al_secret', 'person'),
  a('act_it', 'staff:it', 'open_incident', 'Opened inc_secret', 'person'),
]}));
afterEach(cleanup);

describe('readable action log', () => {
  it('keeps the raw record behind an explicit Details row', () => {
    render(<LogPage />);
    expect(screen.getByText('Cut off MON-06 at the hub')).toBeInTheDocument();
    expect(screen.queryByText(/disable_client/, {selector: 'pre'})).toBeNull();
    const row = screen.getByText('Cut off MON-06 at the hub').closest('tr')!;
    fireEvent.click(within(row).getByRole('button', {name: 'Details'}));
    expect(screen.getByText(/disable_client/, {selector: 'pre'})).toHaveTextContent('act_secret');
    expect(within(row).getByRole('button', {name: 'Details'})).toHaveAttribute('aria-expanded', 'true');
  });
  it('separates People, Agents and IT while searching the human sentence', () => {
    render(<LogPage />);
    fireEvent.click(screen.getByRole('radio', {name: 'People'}));
    expect(screen.getByText('Priya')).toBeInTheDocument();
    expect(screen.queryByText('IT security')).toBeNull();
    expect(screen.queryByText('Network agent')).toBeNull();
    fireEvent.click(screen.getByRole('radio', {name: 'IT'}));
    expect(screen.getByText('IT security')).toBeInTheDocument();
    expect(screen.queryByText('Priya')).toBeNull();
    fireEvent.click(screen.getByRole('radio', {name: 'All'}));
    fireEvent.change(screen.getByRole('searchbox'), {target: {value: 'Network agent'}});
    expect(screen.getByText('Cut off MON-06 at the hub')).toBeInTheDocument();
    expect(screen.queryByText('Acknowledged the alert')).toBeNull();
  });
});
