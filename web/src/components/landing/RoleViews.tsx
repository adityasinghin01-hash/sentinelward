import {useEffect, useRef, useState} from 'react';
import {Activity, ClipboardList, ShieldCheck, Stethoscope, Wrench} from 'lucide-react';
import {prefersReducedMotion} from '../../lib/reveal';
import {useTilt} from '../../lib/tilt';

// Raw night-run timestamps, rather than the historical run-3 row in WARD-RUN.md.
const TIMELINE = [
  {time: '13:49', event: 'DEVICE_ATTACK', detail: 'Network flood'},
  {time: '13:54', event: 'TAMPERING', detail: 'Data untrusted'},
  {time: '14:04', event: 'BOTH', detail: 'Real VFIB arrives'},
  {time: '14:05', event: 'CUT-OFF', detail: 'Monitor disconnected'},
];

// Permissions/routes: web/src/lib/domain.ts; actions: backend/sw_api/app.py.
// B07 receipts: docs/evidence/raw/wardrun-night/timeline_agentsN.txt.
const ROLES = [
  {name: 'Nurse', icon: Stethoscope, step: 2,
    sees: 'Ward / Alerts · B07 “GO NOW” on screen and Telegram.',
    does: 'Acknowledge; go to B07 and check the patient by hand.'},
  {name: 'Doctor', icon: ClipboardList, step: 2,
    sees: 'Census + B07 alert; Telegram at escalation step 3.',
    does: 'Review B07 and acknowledge the emergency.'},
  {name: 'IT security', icon: ShieldCheck, step: 3,
    sees: 'IT Telegram + Incidents · cut-off, evidence and report draft.',
    does: 'Review the evidence; undo the cut-off when appropriate.'},
  // A6 only opens tickets for DRIFTING or repeated LOOSE_SENSOR, not B07's attack.
  {name: 'Biomed', icon: Wrench, step: 3,
    sees: 'Action log · B07 cut-off; no automatic repair ticket.',
    does: 'Inspect the recorded device actions.'},
  {name: 'Operator', icon: Activity, step: 0,
    sees: 'Demo control · hub connection, online beds, rejected messages.',
    does: 'Check system health; run or reset the demo.'},
];

export function RoleViews() {
  const root = useRef<HTMLElement>(null);
  useTilt(root);
  const [active, setActive] = useState(0);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [onscreen, setOnscreen] = useState(() => typeof IntersectionObserver === 'undefined');
  const [visible, setVisible] = useState(() => !document.hidden);
  const [reduced, setReduced] = useState(prefersReducedMotion);

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const motion = () => setReduced(media?.matches ?? false);
    const visibility = () => setVisible(!document.hidden);
    const observer = typeof IntersectionObserver === 'undefined' ? undefined : new IntersectionObserver(entries => {
      setOnscreen(entries.some(entry => entry.isIntersecting));
    }, {threshold: 0.08});
    if (root.current) observer?.observe(root.current);
    media?.addEventListener('change', motion);
    document.addEventListener('visibilitychange', visibility);
    return () => {
      observer?.disconnect();
      media?.removeEventListener('change', motion);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, []);

  useEffect(() => {
    if (reduced || hovered || focused || !onscreen || !visible) return;
    const timer = window.setInterval(() => setActive(index => (index + 1) % ROLES.length), 2800);
    return () => window.clearInterval(timer);
  }, [reduced, hovered, focused, onscreen, visible]);

  return (
    <section className="l-section l-role-views" id="role-views" ref={root} aria-labelledby="l-role-views-title" data-static={reduced}>
      <div className="l-wrap">
        <p className="l-eyebrow" data-reveal>One shared incident · Bed B07</p>
        <h2 className="l-h2" id="l-role-views-title" data-reveal>One event. Five role views.</h2>
        <p className="l-lead" data-reveal>A hacked monitor, then real ventricular fibrillation. The emergency alert stays high while the device is cut off.</p>
        <ol className="l-incident-timeline" aria-label="B07 night run N timeline" data-reveal>
          {TIMELINE.map((step, i) => (
            <li key={step.time} id={`l-b07-step-${i}`} data-active={!reduced && ROLES[active].step === i}>
              <time>{step.time}</time><b>{step.event}</b><span>{step.detail}</span>
            </li>
          ))}
        </ol>
        <div className="l-cards l-role-view-grid" role="group" aria-label="B07 role views"
          onMouseLeave={() => setHovered(false)}
          onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
          {ROLES.map((role, i) => (
            <button type="button" key={role.name} className="l-card l-role-view" data-reveal data-tilt
              aria-labelledby={`l-role-view-${i}`} aria-describedby={`l-role-sees-${i} l-role-does-${i} l-b07-step-${role.step}`}
              aria-pressed={!reduced && active === i}
              onMouseEnter={() => { setHovered(true); setActive(i); }}
              onMouseLeave={() => setHovered(false)}
              onFocus={() => { setFocused(true); setActive(i); }}
              onClick={() => setActive(i)}>
              <span className="l-role-view-head"><span className="l-card-icon"><role.icon size={19} aria-hidden="true" /></span>
                <strong id={`l-role-view-${i}`}>{role.name}</strong><span className="l-role-view-dot" aria-hidden="true" /></span>
              <span className="l-role-view-line" id={`l-role-sees-${i}`}><span className="l-role-view-label">They see</span>{role.sees}</span>
              <span className="l-role-view-line l-role-view-action" id={`l-role-does-${i}`}><span className="l-role-view-label">They do</span>{role.does}</span>
            </button>
          ))}
        </div>
        <p className="l-cite" data-reveal>Night ward run N, build 4348467 · source: <a href="https://github.com/adityasinghin01-hash/sentinelward/blob/main/docs/evidence/WARD-RUN.md" target="_blank" rel="noreferrer">docs/evidence/WARD-RUN.md</a></p>
        <p className="l-cite l-run-source" data-reveal>Times from the <a href="https://github.com/adityasinghin01-hash/sentinelward/blob/main/docs/evidence/raw/wardrun-night/timeline_agentsN.txt" target="_blank" rel="noreferrer">run N action timeline</a> · elapsed minutes:seconds.</p>
      </div>
    </section>
  );
}
