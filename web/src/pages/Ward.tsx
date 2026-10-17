import {useMemo, useRef, useState} from 'react';
import type {KeyboardEvent} from 'react';
import {Link, useNavigate} from 'react-router-dom';
import {Check, ExternalLink} from 'lucide-react';
import {useWard} from '../lib/store';
import {useNow, useCommand} from '../lib/hooks';
import {age, staff, openAlerts} from '../lib/domain';
import type {Alert, Bed} from '../lib/types';
import {BedTile} from '../components/BedTile';
import {ActionList, Feedback, Button, StateChip} from '../components/ui';
import {alertLine, orderBeds, tileView} from '../components/ward/tile';
import type {TileGroup, TileView} from '../components/ward/tile';

const hasSecurityConcern = (bed: Bed) => bed.isolated || bed.verdict === 'BOTH' || bed.verdict === 'TAMPERING' || bed.verdict === 'DEVICE_ATTACK';

const PRIORITY_ORDER = {high: 0, medium: 1, low: 2, none: 3} as const;

function AlertRail({alerts}: {alerts: Alert[]}) {
  const role = useWard(s => s.session?.role);
  const now = useNow();
  const navigate = useNavigate();
  const cmd = useCommand();
  const open = openAlerts(alerts).sort((a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] || b.ts - a.ts);
  const canAck = role === 'nurse' || role === 'doctor'; // matches the backend: nurses and doctors acknowledge
  return (
    <section className="rail-card" aria-label="Open alerts">
      <div className="rail-head"><h2>Open alerts</h2><span className="rail-count">{open.length}</span></div>
      {open.length === 0 ? (
        <p className="rail-empty">No open alerts. New alerts appear here and on the nurse's phone.</p>
      ) : (
        <ul className="alert-list">
          {open.map(a => (
            <li key={a.alert_id} className={`alert-item p-${a.priority}`}>
              <div className="alert-head">
                <Link className="alert-bed" to={`/bed/${a.bed_id}`}>{a.bed_id}</Link>
                <span className="alert-age" title="Time since this alert was raised">{age(a.ts, now)}</span>
              </div>
              <StateChip state={a.verdict} className="alert-chip" />
              <p className="alert-text" title={a.text}>{alertLine(a)}</p>
              <p className="alert-ladder" title="Escalation: 1 = assigned nurse, 2 = next nurse, 3 = all nurses + doctor. Each step waits 30 s in the demo.">
                <span className="ladder-dots" aria-hidden="true">{[1, 2, 3].map(i => <i key={i} className={i <= a.ladder_step ? 'on' : ''} />)}</span>
                Step {a.ladder_step} of 3 · {a.to.map(staff).join(', ') || 'ward'}
              </p>
              <div className="alert-actions">
                <Button variant="primary" size={40} disabled={!canAck || cmd.pending}
                        hint={canAck ? 'I am on it: stops the escalation for this alert.' : 'Only nurses and doctors acknowledge alerts.'}
                        onClick={() => void cmd.run(`/api/beds/${encodeURIComponent(a.bed_id)}/acknowledge`, {type: 'acknowledge_alert', bedId: a.bed_id, alertId: a.alert_id})}>
                  <Check size={15} aria-hidden="true" /> Acknowledge
                </Button>
                <Button variant="secondary" size={40} onClick={() => navigate(`/bed/${a.bed_id}`)} hint="Open this bed: readings, the checks and the evidence.">
                  <ExternalLink size={14} aria-hidden="true" /> Open
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Feedback message={cmd.feedback} failed={cmd.failed} />
    </section>
  );
}

const FILTERS: {key: TileGroup | 'all'; label: string; dot: string}[] = [
  {key: 'all', label: 'All beds', dot: ''},
  {key: 'emergency', label: 'Emergency', dot: 'emergency'},
  {key: 'security', label: 'Security concern', dot: 'security'},
  {key: 'check', label: 'Check by hand', dot: 'check'},
  {key: 'nosignal', label: 'No signal', dot: 'nodata'},
  {key: 'normal', label: 'Normal', dot: 'ok'},
];

export function WardPage() {
  const beds = useWard(s => s.beds);
  const alerts = useWard(s => s.alerts);
  const actions = useWard(s => s.actions);
  const hidden = useWard(s => s.hidden);
  const error = useWard(s => s.error);
  const now = useNow();
  const navigate = useNavigate();
  const grid = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState<TileGroup | 'all'>('all');

  const views = useMemo(() => new Map<string, TileView>(beds.map(b => [b.bed_id, tileView(b, alerts, now)])), [beds, alerts, now]);
  const ordered = useMemo<Bed[]>(() => orderBeds(beds, views), [beds, views]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {all: beds.length};
    for (const v of views.values()) c[v.group] = (c[v.group] || 0) + 1;
    // Security overlaps emergency: count the underlying concern, even with a high alert open.
    c.security = beds.filter(hasSecurityConcern).length;
    c.check = (c.check || 0) + (c.maint || 0);
    return c;
  }, [views, beds]);
  const visible = ordered.filter(b => {
    const v = views.get(b.bed_id)!;
    return filter === 'all' || v.group === filter || (filter === 'security' && hasSecurityConcern(b)) || (filter === 'check' && v.group === 'maint');
  });

  // Arrow keys move between tiles in reading order; Enter opens the bed (links handle Enter).
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const tiles = Array.from(grid.current?.querySelectorAll<HTMLAnchorElement>('.tile-link') ?? []);
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
      <div className="ward-strip" role="toolbar" aria-label="Filter beds by state">
        <span className="strip-title">Ward</span>
        {FILTERS.map(f => (
          <button key={f.key} className="strip-btn" aria-pressed={filter === f.key} onClick={() => setFilter(filter === f.key && f.key !== 'all' ? 'all' : f.key)}>
            {f.dot && <span className={`dot ${f.dot}`} aria-hidden="true" />}{f.label}<b>{counts[f.key] || 0}</b>
          </button>
        ))}
        <span className="strip-meta">Problem beds first · click a bed to open it</span>
      </div>
      {error && <p className="notice" role="status">{error} The last received information stays on screen.</p>}
      <div className="ward-layout">
        {beds.length === 0 ? (
          <div className="bed-grid" aria-busy="true">{Array.from({length: 12}, (_, i) => <div key={i} className="skeleton-tile" />)}</div>
        ) : (
          <div className="bed-grid" ref={grid} onKeyDown={onKey} aria-label="Beds. Use arrow keys to move, Enter to open.">
            {visible.map(b => <BedTile key={b.bed_id} bed={b} hidden={hidden} now={now} alerts={alerts} />)}
            {visible.length === 0 && <p className="ward-filter-empty" role="status">No beds match this filter.</p>}
          </div>
        )}
        <aside className="ward-rail">
          <AlertRail alerts={alerts} />
          <section className="rail-card" aria-label="Recent events">
            <div className="rail-head"><h2>Recent events</h2><button className="strip-btn" onClick={() => navigate('/log')}>Full log</button></div>
            <ActionList actions={actions.slice(0, 6)} />
          </section>
        </aside>
      </div>
    </div>
  );
}
