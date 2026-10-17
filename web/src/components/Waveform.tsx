import {useEffect, useRef} from 'react';
import {seriesColour, useThemeTokens} from '../lib/theme';

/** Monotone cubic interpolation passes through every sample without adding peaks. */
export function Waveform({samples, label = 'ECG', frozen = false, large = false, frozenLabel = 'Last trusted recording, held still.'}: {
  samples: number[]; label?: string; frozen?: boolean; large?: boolean; frozenLabel?: string;
}) {
  const tokens = useThemeTokens();
  const ref = useRef<HTMLCanvasElement>(null);
  const lead = /^ecg$/i.test(label) ? 'ECG II' : /^pleth$/i.test(label) ? 'Pleth' : /^abp$/i.test(label) ? 'ABP mmHg' : label;
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const draw = () => {
      const width = canvas.clientWidth, height = canvas.clientHeight, dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
      const c = canvas.getContext('2d');
      if (!c) return;
      c.scale(dpr, dpr);
      c.clearRect(0, 0, width, height);
      c.strokeStyle = tokens['--wave-grid'];
      // One major square contains five minor squares, as on a bedside monitor.
      for (const major of [false, true]) {
        const step = major ? 40 : 8;
        c.lineWidth = major ? .8 : .4;
        c.beginPath();
        for (let x = .5; x < width; x += step) { c.moveTo(x, 0); c.lineTo(x, height); }
        for (let y = .5; y < height; y += step) { c.moveTo(0, y); c.lineTo(width, y); }
        c.stroke();
      }
      if (!samples.length) return;
      const lo = Math.min(...samples), hi = Math.max(...samples), range = hi - lo || 1;
      const top = large ? 28 : height * .14, bottom = height * .86;
      const ys = samples.map(v => bottom - (v - lo) / range * (bottom - top));
      const dx = width / Math.max(1, samples.length - 1);
      const slopes = ys.slice(1).map((y, i) => y - ys[i]);
      const tangent = (i: number) => {
        if (i === 0) return slopes[0] ?? 0;
        if (i === ys.length - 1) return slopes[i - 1] ?? 0;
        const a = slopes[i - 1], b = slopes[i];
        return a * b <= 0 ? 0 : 2 * a * b / (a + b);
      };
      c.strokeStyle = frozen ? tokens['--wave-frozen'] : seriesColour(label, tokens);
      c.lineWidth = large ? 1.8 : 1.3;
      c.lineJoin = 'round'; c.lineCap = 'round';
      c.beginPath(); c.moveTo(0, ys[0]);
      for (let i = 1; i < ys.length; i++) {
        c.bezierCurveTo((i - 1 + 1 / 3) * dx, ys[i - 1] + tangent(i - 1) / 3,
          (i - 1 / 3) * dx, ys[i] - tangent(i) / 3, i * dx, ys[i]);
      }
      c.stroke();
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [samples, label, frozen, large, tokens]);
  const signal = /abp/i.test(label) ? 'Arterial pressure signal' : /pleth/i.test(label) ? 'Finger pulse signal' : 'Heart electrical signal';
  return <div className={`waveform ${large ? 'wave-large' : ''}`}>
    <span className="wave-label">{lead}</span>
    <canvas ref={ref} role="img" aria-label={`${signal}. ${frozen ? frozenLabel : 'Most recent received samples.'}${!samples.length ? ' No samples received.' : ''}`} />
    {!samples.length && <span className="wave-empty">Awaiting first signal</span>}
  </div>;
}
