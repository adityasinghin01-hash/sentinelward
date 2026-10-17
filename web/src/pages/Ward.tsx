import {useMemo, useRef} from 'react';
import type {KeyboardEvent} from 'react';
import {useNavigate} from 'react-router-dom';
import {Eye, EyeOff, Bell, Check, ExternalLink} from 'lucide-react';
import {useWard} from '../lib/store';
import {useNow, useCommand} from '../lib/hooks';
import {bedState, time, age} from '../lib/domain';
import type {Alert, Bed} from '../lib/types';
import {BedTile} from '../components/BedTile';
import {Stats, Panel, Badge, ActionList, Empty, Feedback, BedLink} from '../components/ui';

const PRIORITY_ORDER = {high: 0, medium: 1, low: 2, none: 3} as const;

function AlertRail({alerts, beds}: {alerts: Alert[]; beds: Bed[]}) {
  const role = useWard(s => s.session?.role);
  const now = useNow();
  const navigate = useNavigate();
  const cmd = useCommand();
  const open = alerts
    .filter(a => a.status === 'open' || a.status === 'escalated')
    .sort((a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] || b.ts - a.ts);
  const canAck = role === 'nurse' || role === 'operator';
  return (
    <Panel title="Active alerts" caption="One alert per bed per event; repeats update it, never stack."
           aside={<Badge tone={open.some(a => a.priority === 'high') ? 'high' : 'none'}>{open.length} open</Badge>}>
      {open.length === 0 ? (
        <Empty title="No open alerts" detail="When the AI raises an alert it appears here and on the nurse's phone." />
      ) : (
        <ul className="alert-list">
          {open.map(a => {
            const bed = beds.find(b => b.bed_id === a.bed_id);
            return (
              <li key={a.alert_id} className={`alert-item alarm-edge-${a.priority}`}>
                <div className="alert-head">
                  <Badge tone={a.priority}>{a.verdict.replace('_', ' ')}</Badge>
                  <BedLink id={a.bed_id} />
                  <span className="alert-age" title="Time since this alert was raised">{age(a.ts, now)}</span>
                </div>
                <p className="alert-text">{a.text}</p>
                <p className="alert-ladder" title="Escalation ladder: 1 = assigned nurse, 2 = next nurse, 3 = all nurses + doctor. Each step waits 30 s in the demo.">
                  <Bell size={12} aria-hidden="true" /> Ladder step {a.ladder_step} of 3 · sent to {a.to.join(', ') || 'ward'}
                  {bed && !bed.is_trusted && ' · do not trust screen numbers'}
                </p>
                <div className="alert-actions">
                  <button className="button-small" disabled={!canAck || cmd.pending}
                          title={canAck ? 'I am on it: stops the escalation ladder for this alert.' : 'Only the nurse acknowledges alerts.'}
                          onClick={() => void cmd.run(`/api/beds/${encodeURIComponent(a.bed_id)}/acknowledge`, {type: 'acknowledge_alert', bedId: a.bed_id, alertId: a.alert_id})}>
                    <Check size={13} aria-hidden="true" /> Acknowledge
                  </button>
                  <button className="button-small ghost" onClick={() => navigate(`/bed/${a.bed_id}`)}
                          title="Open this bed's readings, the six AI checks and the evidence.">
                    <ExternalLink size={13} aria-hidden="true" /> Open bed
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <Feedback message={cmd.feedback} failed={cmd.failed} />
    </Panel>
  );
}

export function WardPage() {
  const beds = useWard(s => s.beds);
  const alerts = useWard(s => s.alerts);
  const actions = useWard(s => s.actions);
  const hidden = useWard(s => s.hidden);
  const toggleHidden = useWard(s => s.setHidden);
  const error = useWard(s => s.error);
  const now = useNow();
  const navigate = useNavigate();
  const grid = useRef<HTMLDivElement>(null);

  const summary = useMemo(() => {
    const states = beds.map(b => bedState(b, now));
    const alarming = beds.filter(b => b.priority === 'high' || b.priority === 'medium').length;
    const untrusted = states.filter(s => s.untrusted).length;
    const trusts = beds.map(b => b.trust_score).filter(t => typeof t === 'number');
    const avg = trusts.length ? trusts.reduce((x, y) => x + y, 0) / trusts.length / 100 : null;
    return {alarming, untrusted, avg, offline: states.filter(s => s.offline).length};
  }, [beds, now]);

  // Arrow keys move between tiles in reading order; Enter opens the bed (links handle Enter).
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const tiles = Array.from(grid.current?.querySelectorAll<HTMLAnchorElement>('.bed-title') ?? []);
    const i = tiles.indexOf(document.activeElement as HTMLAnchorElement);
    if (i < 0) return;
    const cols = getComputedStyle(grid.current!).gridTemplateColumns.split(' ').length;
    const step = {ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols}[e.key];
    if (step === undefined) return;
    e.preventDefault();
    tiles[Math.min(tiles.length - 1, Math.max(0, i + step))]?.focus();
  };

  return (
    <div className="page ward-page">
      <div className="ward-summary">
        <Stats items={[
          {label: 'Beds', value: beds.length, hint: 'Beds this station is watching.', sub: summary.offline ? `${summary.offline} with no data now` : 'all reporting'},
          {label: 'Alarms now', value: summary.alarming, hint: 'Beds whose current verdict needs a person (high or medium priority).'},
          {label: 'Untrusted', value: summary.untrusted, hint: 'Beds whose incoming data is not trusted; the screen shows their last trusted values instead.'},
          {label: 'Average trust', value: summary.avg === null ? '—' : summary.avg.toFixed(2), hint: 'Mean data-trust score across beds, 0 to 1. Higher means the readings are more likely genuine.'},
        ]} />
        <button className="toggle" onClick={toggleHidden} aria-pressed={!hidden}
                title={hidden ? 'Show patient initials, age and sex on the tiles.' : 'Hide patient details (privacy default).'}>
          {hidden ? <EyeOff size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
          {hidden ? 'Names hidden' : 'Names shown'}
        </button>
      </div>
      {error && <p className="notice" role="status">{error} The last received information stays on screen.</p>}
      <div className="ward-layout">
        {beds.length === 0 ? (
          <div className="bed-grid skeleton-grid" aria-busy="true">
            {Array.from({length: 12}, (_, i) => <div key={i} className="bed-tile skeleton-tile" />)}
          </div>
        ) : (
          <div className="bed-grid" ref={grid} onKeyDown={onKey} aria-label="Bed tiles. Use arrow keys to move, Enter to open.">
            {beds.map(b => <BedTile key={b.bed_id} bed={b} hidden={hidden} now={now} />)}
          </div>
        )}
        <aside className="ward-rail">
          <AlertRail alerts={alerts} beds={beds} />
          <Panel title="Recent events" caption={`Automatic and staff actions · updated ${time(now)}`}>
            <ActionList actions={actions.slice(0, 8)} />
            {actions.length > 8 && (
              <button className="button-small ghost" onClick={() => navigate('/log')} title="See all actions with undo.">
                Full action log
              </button>
            )}
          </Panel>
        </aside>
      </div>
    </div>
  );
}
