import {useEffect, useRef} from 'react';

// Illustrative signal states, not live measurements from the decorative monitor.
const SIGNALS = [
  {tone: 'ok', text: 'TLS 1.3 · secured hub'},
  {tone: 'check', text: 'SpO₂ lead off · sensor'},
  {tone: 'security', text: 'Replayed frame · security'},
  {tone: 'emergency', text: 'VF · real emergency'},
];

export function SignalChips() {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    let onscreen = typeof IntersectionObserver === 'undefined';
    const sync = () => el.toggleAttribute('data-paused', !onscreen || document.hidden);
    const observer = typeof IntersectionObserver === 'undefined' ? undefined : new IntersectionObserver(entries => {
      onscreen = entries.some(entry => entry.isIntersecting);
      sync();
    });
    observer?.observe(el.closest('.l-hero-art') ?? el);
    document.addEventListener('visibilitychange', sync);
    sync();
    return () => { observer?.disconnect(); document.removeEventListener('visibilitychange', sync); };
  }, []);
  return (
    <div className="l-signal-chips" ref={root} aria-hidden="true">
      {SIGNALS.map(signal => <span key={signal.tone} className={`l-signal-chip l-signal-${signal.tone}`}><span><i />{signal.text}</span></span>)}
    </div>
  );
}
