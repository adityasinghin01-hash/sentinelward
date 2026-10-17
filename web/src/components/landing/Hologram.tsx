import {useEffect, useRef} from 'react';

// Hero hologram (DESIGN-SPEC §10, research-codex C3): CSS 3D + SVG only.
// Decorative: aria-hidden, pauses offscreen / when the tab is hidden, static under reduced motion.

/** One PQRST complex per 80 units, baseline y = 56, for a 320 × 90 viewBox. */
export function ecgPath(beats = 4, width = 80): string {
  let d = 'M0 56';
  for (let i = 0; i < beats; i++) {
    const x = i * width;
    d += ` L${x + 10} 56 Q${x + 17} 47 ${x + 24} 56 L${x + 30} 56 L${x + 33} 61 L${x + 37} 12`
      + ` L${x + 41} 71 L${x + 45} 56 L${x + 52} 56 Q${x + 60} 41 ${x + 68} 56 L${x + width} 56`;
  }
  return d;
}

/** Pleth-like smooth wave, 4 pulses over 320 units, baseline y = 30 in a 320 × 44 viewBox. */
export function plethPath(beats = 4, width = 80): string {
  let d = 'M0 34';
  for (let i = 0; i < beats; i++) {
    const x = i * width;
    d += ` C${x + 14} 34 ${x + 18} 8 ${x + 30} 9 C${x + 40} 10 ${x + 42} 22 ${x + 48} 21`
      + ` C${x + 54} 20 ${x + 60} 32 ${x + width} 34`;
  }
  return d;
}

const CHECKS = ['Sensor', 'Alarm', 'Body', 'Replay', 'Network', 'Drift'];

export function Hologram({paused = false}: {paused?: boolean}) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    let onscreen = true;
    const sync = () => {
      if (onscreen && !document.hidden && !paused) el.removeAttribute('data-paused');
      else el.setAttribute('data-paused', '');
    };
    let io: IntersectionObserver | undefined;
    if (typeof IntersectionObserver !== 'undefined') {
      io = new IntersectionObserver(([entry]) => { onscreen = entry.isIntersecting; sync(); });
      io.observe(el);
    }
    sync();
    document.addEventListener('visibilitychange', sync);
    return () => { io?.disconnect(); document.removeEventListener('visibilitychange', sync); };
  }, [paused]);

  const ecg = ecgPath();
  const pleth = plethPath();
  return (
    <div className="holo" ref={root} aria-hidden="true" data-testid="hologram">
      <div className="holo-glow" />
      <div className="holo-stage">
        <div className="holo-assembly">
          <div className="holo-plane holo-plane-back" />
          <div className="holo-plane holo-plane-mid" />
          <div className="holo-panel">
            <div className="holo-head">
              <span className="holo-bed">Bed B03</span>
              <span className="holo-live"><i />Live</span>
            </div>
            <div className="holo-trace">
              <span className="holo-label">ECG II</span>
              <svg viewBox="0 0 320 90" preserveAspectRatio="none">
                <path className="holo-base" d={ecg} pathLength={1000} />
                <path className="holo-comet holo-comet-ecg" d={ecg} pathLength={1000} />
              </svg>
            </div>
            <div className="holo-trace holo-trace-sm">
              <span className="holo-label">Pleth</span>
              <svg viewBox="0 0 320 44" preserveAspectRatio="none">
                <path className="holo-base holo-base-pleth" d={pleth} pathLength={1000} />
                <path className="holo-comet holo-comet-pleth" d={pleth} pathLength={1000} />
              </svg>
            </div>
            <div className="holo-verdict"><i />Normal · signal trusted</div>
            <ul className="holo-checks">
              {CHECKS.map((c, i) => (
                <li key={c}><span>{c}</span><b style={{width: `${[14, 22, 10, 8, 12, 18][i]}%`}} /></li>
              ))}
            </ul>
            <div className="holo-scan" />
          </div>
        </div>
      </div>
    </div>
  );
}
