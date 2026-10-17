import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {Waveform} from './Waveform';

afterEach(() => {cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();});
it('smoothly draws every sample at device resolution and labels the lead', () => {
  const context = {scale: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), bezierCurveTo: vi.fn(), stroke: vi.fn()};
  vi.spyOn(HTMLCanvasElement.prototype, 'clientWidth', 'get').mockReturnValue(600);
  vi.spyOn(HTMLCanvasElement.prototype, 'clientHeight', 'get').mockReturnValue(120);
  vi.stubGlobal('devicePixelRatio', 2);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
  const samples = [0, 1, .2, 0, .8];
  render(<Waveform samples={samples} large />);
  expect(screen.getByText('ECG II')).toBeInTheDocument();
  const canvas = screen.getByRole('img') as HTMLCanvasElement;
  expect(canvas.width).toBe(1200);
  expect(canvas.height).toBe(240);
  expect(context.bezierCurveTo).toHaveBeenCalledTimes(samples.length - 1);
  expect(context.bezierCurveTo.mock.calls.map(args => args[4])).toEqual([150, 300, 450, 600]);
  expect(samples).toEqual([0, 1, .2, 0, .8]);
});
it('names pressure and its unit without inventing a reading', () => {
  render(<Waveform samples={[]} label="ABP" large frozen />);
  expect(screen.getByText('ABP mmHg')).toBeInTheDocument();
  expect(screen.getByText('Awaiting first signal')).toBeInTheDocument();
});
