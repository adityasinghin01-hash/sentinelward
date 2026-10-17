import {useEffect, useRef} from 'react';
import {useThemeTokens, seriesColour} from '../lib/theme';

export interface Series {label: string; color: string; values: (number | null)[]; unit?: string}

/**
 * Time-series lines on <canvas> (fast for long histories). Spans marked untrusted are shaded with
 * grey diagonal stripes, the same pattern the bed tiles use. Each series is scaled to its own range
 * so lines with different units can share one chart; the legend gives the latest value and unit.
 */
export function TrendChart({ts, series, untrusted, height = 150, label}: {
  ts: number[]; series: Series[]; untrusted?: boolean[]; height?: number; label: string;
}) {
  const tokens = useThemeTokens();
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const draw = () => {
      const width = canvas.clientWidth, h = canvas.clientHeight, dpr = window.devicePixelRatio || 1;
      canvas.width = width * dpr; canvas.height = h * dpr;
      const c = canvas.getContext('2d');
      if (!c) return;
      c.scale(dpr, dpr);
      c.clearRect(0, 0, width, h);
      c.strokeStyle = tokens['--wave-grid'];
      c.lineWidth = 1;
      for (let y = 0; y <= 4; y++) { c.beginPath(); c.moveTo(0, 8 + y * (h - 16) / 4); c.lineTo(width, 8 + y * (h - 16) / 4); c.stroke(); }
      if (ts.length < 2) return;
      const t0 = ts[0], t1 = ts[ts.length - 1], span = t1 - t0 || 1;
      const x = (t: number) => (t - t0) / span * width;
      if (untrusted) {
        const pattern = document.createElement('canvas');
        pattern.width = pattern.height = 10;
        const p = pattern.getContext('2d');
        if (p) {
          p.strokeStyle = tokens['--wave-frozen']; p.lineWidth = 3;
          p.beginPath(); p.moveTo(0, 10); p.lineTo(10, 0); p.stroke();
          const fill = c.createPattern(pattern, 'repeat');
          if (fill) {
            c.fillStyle = fill;
            let start = -1;
            untrusted.forEach((u, i) => {
              if (u && start < 0) start = i;
              if ((!u || i === untrusted.length - 1) && start >= 0) {
                c.fillRect(x(ts[start]), 0, Math.max(2, x(ts[i]) - x(ts[start])), h);
                start = -1;
              }
            });
          }
        }
      }
      for (const s of series) {
        const nums = s.values.filter((v): v is number => typeof v === 'number');
        if (!nums.length) continue;
        let lo = Math.min(...nums), hi = Math.max(...nums);
        if (hi - lo < 10) { const mid = (hi + lo) / 2; lo = mid - 5; hi = mid + 5; }
        const y = (v: number) => h - 10 - (v - lo) / (hi - lo) * (h - 20);
        c.strokeStyle = seriesColour(s.label,tokens); c.lineWidth = 1.6; c.beginPath();
        let pen = false;
        s.values.forEach((v, i) => {
          if (typeof v !== 'number') { pen = false; return; }
          if (!pen) { c.moveTo(x(ts[i]), y(v)); pen = true; } else c.lineTo(x(ts[i]), y(v));
        });
        c.stroke();
      }
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [ts, series, untrusted, tokens]);
  return (
    <div className="trend" style={{height}}>
      <canvas ref={ref} role="img" aria-label={label} />
      {ts.length < 2 && <span className="wave-empty">No history recorded in this window</span>}
    </div>
  );
}
