import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {TrendChart} from './Chart';

afterEach(cleanup);
it('gives each vital its own scale, units, current value and five-minute time labels', () => {
  const start = new Date(2026, 9, 18, 2, 0).getTime();
  render(<TrendChart ts={[start, start + 300_000, start + 600_000]} label="Bed trends"
    series={[{label: 'HR', unit: 'bpm', color: '', values: [70, 80, 90]}, {label: 'SpO₂', unit: '%', color: '', values: [96, 97, 98]}]}
    untrusted={[false, true, true]} />);
  expect(screen.getByText('HR')).toBeInTheDocument();
  expect(screen.getByText('SpO₂')).toBeInTheDocument();
  expect(screen.getByLabelText('Current HR: 90 bpm')).toBeInTheDocument();
  expect(screen.getByLabelText('Current SpO₂: 98 %')).toBeInTheDocument();
  expect(screen.getByText('02:05')).toBeInTheDocument();
  expect(screen.getAllByText('Not trusted').length).toBeGreaterThan(0);
});
it('shows a dash for a missing current sample instead of promoting an older value', () => {
  render(<TrendChart ts={[1, 2]} series={[{label: 'BP', unit: 'mmHg', color: '', values: [120, null]}]} label="Pressure" />);
  expect(screen.getByLabelText('Current BP: — mmHg')).toBeInTheDocument();
});
it('does not connect across a missing reading', () => {
  const context = {scale: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), fillRect: vi.fn(), arc: vi.fn(), fill: vi.fn()};
  const spy = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
  render(<TrendChart ts={[1, 2, 3]} series={[{label: 'HR', color: '', values: [70, null, 90]}]} label="Heart rate" />);
  // Grid lines precede the series; both isolated samples must start a new path.
  expect(context.moveTo.mock.calls.slice(-2)).toEqual([[0, expect.any(Number)], [0, expect.any(Number)]]);
  // Two horizontal grid lines, no line joining the two isolated readings.
  expect(context.lineTo).toHaveBeenCalledTimes(2);
  spy.mockRestore();
});
