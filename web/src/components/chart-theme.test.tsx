import {act,cleanup,render} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {Waveform} from './Waveform';
import {TrendChart} from './Chart';
import {applyTheme} from '../lib/theme';
let strokes:string[];
let context:CanvasRenderingContext2D;
const samples=[0,1,0];
function colours(suffix:string){for(const name of ['ecg','pleth','abp','grid','frozen'])document.documentElement.style.setProperty(`--wave-${name}`,`${name}-${suffix}`)}
beforeEach(()=>{
  strokes=[];
  context={scale:vi.fn(),clearRect:vi.fn(),beginPath:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),bezierCurveTo:vi.fn(),arc:vi.fn(),fill:vi.fn(),stroke:vi.fn(),set strokeStyle(value:string){strokes.push(value)}} as unknown as CanvasRenderingContext2D;
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(context);
  colours('day');applyTheme('light');
});
afterEach(()=>{cleanup();vi.restoreAllMocks();document.documentElement.removeAttribute('style')});
it.each([false,true])('redraws a waveform from current tokens without changing samples or frozen=%s',frozen=>{
  render(<Waveform samples={samples} frozen={frozen}/>);
  expect(strokes.at(-1)).toBe(frozen?'frozen-day':'ecg-day');
  const before=vi.mocked(context.lineTo).mock.calls.slice();
  colours('night');act(()=>applyTheme('dark'));
  expect(strokes.at(-1)).toBe(frozen?'frozen-night':'ecg-night');
  expect(vi.mocked(context.lineTo).mock.calls.slice(before.length)).toEqual(before);
  expect(samples).toEqual([0,1,0]);
});
it('redraws ECG, pleth and pressure trends with distinct theme tokens',()=>{
  render(<TrendChart ts={[1,2]} series={['HR','SpO₂','BP sys'].map(label=>({label,color:'legacy colour',values:[0,1]}))} label="Vitals history"/>);
  expect(strokes.slice(-3)).toEqual(['ecg-day','pleth-day','abp-day']);
  colours('night');act(()=>applyTheme('dark'));
  expect(strokes.slice(-3)).toEqual(['ecg-night','pleth-night','abp-night']);
});
