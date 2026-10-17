import {useEffect, useRef} from 'react';
import {useThemeTokens, seriesColour} from '../lib/theme';

export interface Series {label: string; color: string; values: (number | null)[]; unit?: string}
const FIVE_MINUTES = 5 * 60_000;
const clock = (ts: number) => new Date(ts).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false});
const reading = (n: number | null | undefined) => typeof n === 'number' && Number.isFinite(n) ? String(Math.round(n * 10) / 10) : '—';

function bounds(values: (number | null)[]) {
  const nums = values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (!nums.length) return null;
  const min = Math.min(...nums), max = Math.max(...nums);
  const pad = Math.max(5, (max - min) * .12);
  return {lo: Math.floor((min - pad) / 5) * 5, hi: Math.ceil((max + pad) / 5) * 5};
}

/** Independent scales keep unlike units readable; null samples remain gaps. */
export function TrendChart({ts, series, untrusted, height = 94, label}: {
  ts: number[]; series: Series[]; untrusted?: boolean[]; height?: number; label: string;
}) {
  const tokens = useThemeTokens();
  const ref = useRef<HTMLCanvasElement>(null);
  const t0 = ts[0] ?? 0, t1 = ts.at(-1) ?? t0, span = t1 - t0 || 1;
  const percent = (t: number) => Math.max(0, Math.min(100, (t - t0) / span * 100));
  const ticks: number[] = [];
  for (let t = Math.ceil(t0 / FIVE_MINUTES) * FIVE_MINUTES; t <= t1; t += FIVE_MINUTES) ticks.push(t);
  const ranges: {start: number; end: number}[] = [];
  let start = -1;
  for (let i = 0; i < ts.length; i++) {
    if (untrusted?.[i] && start < 0) start = i;
    if (start >= 0 && (!untrusted?.[i] || i === ts.length - 1)) {
      ranges.push({start: percent(ts[start]), end: percent(ts[i])}); start = -1;
    }
  }
  const scales = series.map(s => bounds(s.values));
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const draw = () => {
      const width = canvas.clientWidth, h = canvas.clientHeight, dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(h * dpr);
      const c = canvas.getContext('2d');
      if (!c) return;
      c.scale(dpr, dpr); c.clearRect(0, 0, width, h);
      c.strokeStyle = tokens['--wave-grid']; c.lineWidth = 1;
      for (let row = 0; row < series.length; row++) {
        for (const offset of [30, height - 12]) {
          c.beginPath(); c.moveTo(0, row * height + offset); c.lineTo(width, row * height + offset); c.stroke();
        }
      }
      if (ts.length < 2) return;
      const x = (t: number) => (t - t0) / span * width;
      for (let row = 0; row < series.length; row++) {
        const s = series[row], scale = scales[row];
        if (!scale) continue;
        const y = (v: number) => row * height + height - 12 - (v - scale.lo) / (scale.hi - scale.lo) * (height - 42);
        c.strokeStyle = seriesColour(s.label, tokens); c.lineWidth = 1.7; c.beginPath();
        let pen = false;
        s.values.forEach((v, i) => {
          if (typeof v !== 'number' || !Number.isFinite(v) || ts[i] === undefined) { pen = false; return; }
          if (!pen) { c.moveTo(x(ts[i]), y(v)); pen = true; } else c.lineTo(x(ts[i]), y(v));
        });
        c.stroke();
        const current = s.values.at(-1);
        if (typeof current === 'number' && Number.isFinite(current)) {
          c.fillStyle = seriesColour(s.label, tokens); c.beginPath();
          c.arc(x(t1), y(current), 2.5, 0, Math.PI * 2); c.fill();
        }
      }
    };
    draw();
    const observer = new ResizeObserver(draw); observer.observe(canvas);
    return () => observer.disconnect();
  }, [ts, series, untrusted, tokens, height]);
  return <div className="trend-multiples" aria-label={label}>
    <div className="trend-body" style={{height: series.length * height}}>
      <div className="trend-plot">
        {ranges.map((r, i) => <div className="trend-untrusted" key={i} style={{left: `${r.start}%`, width: `${Math.max(.3, r.end - r.start)}%`}} title="Not trusted" />)}
        {ticks.map(t => <i className="trend-time-grid" key={t} style={{left: `${percent(t)}%`}} />)}
        <canvas ref={ref} role="img" aria-label={`${label}. Each row has its own labelled scale and unit. Shaded periods are not trusted.`} />
      </div>
      <span className="trend-latest">Latest</span>
      {series.map((s, i) => <div className="trend-series" key={s.label} style={{top: i * height, height}}>
        <div className="trend-series-name"><i style={{background: seriesColour(s.label, tokens)}} /><b>{s.label}</b><span>{s.unit}</span></div>
        {scales[i] && <><span className="trend-y trend-y-high mono">{scales[i]!.hi}</span><span className="trend-y trend-y-low mono">{scales[i]!.lo}</span></>}
        <span className="trend-current mono" aria-label={`Current ${s.label}: ${reading(s.values.at(-1))} ${s.unit ?? ''}`}><b>{reading(s.values.at(-1))}</b><small>{s.unit}</small></span>
        {!scales[i] && <span className="trend-no-values">No readings in this window</span>}
      </div>)}
    </div>
    <div className="trend-time-axis">
      {ts.length > 1 ? (ticks.length ? ticks : [t0, t1]).map(t => <time className="mono" key={t} style={{left: `${percent(t)}%`}}>{clock(t)}</time>) : <span>No history recorded in this window</span>}
    </div>
    {!!ranges.length && <div className="trend-key"><i />Not trusted</div>}
  </div>;
}
