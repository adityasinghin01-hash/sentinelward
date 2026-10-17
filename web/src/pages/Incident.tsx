import {useState} from 'react';
import {Link, useParams} from 'react-router-dom';
import {Camera, CheckCircle2, FileText, Lock, ShieldAlert} from 'lucide-react';
import {useWard} from '../lib/store';
import {useCommand, useNow, useResource} from '../lib/hooks';
import {can, certDeadline, countdown, dateTime, time} from '../lib/domain';
import type {AgentRecord} from '../lib/types';
import {BedLink, Button, Chip, ConfirmDialog, Dialog, Empty, Feedback, Panel, ResourceState, Stats} from '../components/ui';
import {PageHeader} from '../components/pages/PageHeader';
import {ActionFeed} from '../components/pages/ActionRecord';
import {actionView, actorName, plainText} from '../components/pages/actions';
import {EvidenceRecord} from '../components/pages/EvidenceRecord';
import {timelineView} from '../components/pages/timeline';

const title = (d: Record<string, unknown>) => `${plainText(String(d.attack_type ?? d.title ?? 'Suspected attack').replace(/_/g, ' ')).replace(/^./, c => c.toUpperCase())} · ${String(d.device_id ?? 'Monitor')} · ${String(d.bed_id ?? 'Bed not recorded')}`;
export function IncidentListPage() {
  const list = useResource<AgentRecord[]>('/api/incidents', 8000);
  const rows = list.data ?? [];
  return <div className="page pages-page incidents-page">
    <PageHeader title="Incidents" description="Security investigations, their status, and the evidence kept for each monitor." />
    <ResourceState loading={list.loading && !list.data} error={list.error} retry={() => void list.reload()} />
    <Panel title={list.data ? `${rows.length} incident${rows.length === 1 ? '' : 's'}` : 'Incident records'}>
      {!rows.length && list.data ? <Empty title="No incidents recorded" detail="The evidence agent opens an incident when a monitor may be under attack."><Link to="/security" className="button-link">Back to Security</Link></Empty> :
        <ul className="incident-list pages-incident-list">{rows.map(r => <li key={r.record_id}><span className="incident-list-icon"><ShieldAlert size={18} aria-hidden="true" /></span>
          <div><Link className="inline-link" to={`/incident/${encodeURIComponent(r.record_id)}`}>{title(r.data)}</Link><p className="tiny">Opened <time className="mono">{dateTime(r.ts)}</time></p></div>
          <Chip>{plainText(String(r.data.status ?? 'open').replace(/_/g, ' '))}</Chip>
        </li>)}</ul>}
    </Panel>
  </div>;
}

export function IncidentPage() {
  const {incidentId = ''} = useParams();
  const role = useWard(s => s.session?.role);
  const actions = useWard(s => s.actions);
  const now = useNow();
  const inc = useResource<AgentRecord>(`/api/incidents/${encodeURIComponent(incidentId)}`, 5000);
  const reports = useResource<AgentRecord[]>('/api/reports', 10000);
  const report = reports.data?.find(r => r.data.incident_id === incidentId || r.record_id === incidentId) ?? null;
  const capture = useCommand();
  const contain = useCommand();
  const resolve = useCommand();
  const [containing, setContaining] = useState(false);
  const [closing, setClosing] = useState(false);
  const [reason, setReason] = useState('');
  if (!inc.data) return <div className="page pages-page"><PageHeader title="Incident" description="The investigation timeline and its evidence." />
    {inc.error && !inc.loading ? <Empty title="Incident could not be loaded" detail="The record may no longer be available. Return to Security to see current incidents."><Link to="/security" className="button-link">Back to Security</Link></Empty> : <ResourceState loading error="" />}
  </div>;
  const d = inc.data.data;
  const bedId = String(d.bed_id ?? '');
  const deviceId = String(d.device_id ?? '');
  const status = String(d.status ?? 'open');
  const closed = ['resolved', 'closed'].includes(status);
  const evidence = (Array.isArray(d.evidence) ? d.evidence : []) as Record<string, unknown>[];
  const due = certDeadline(report, inc.data) ?? inc.data.ts + 6 * 3600_000;
  const attackStart = Number(d.attack_start_ts ?? d.detected_ts) || inc.data.ts;
  const related = actions.filter(a => (bedId && a.bed_id === bedId) || (deviceId && a.device_id === deviceId)).filter(a => a.occurred_at >= inc.data!.ts - 60_000);
  const own = (Array.isArray(d.timeline) ? d.timeline : []) as Record<string, unknown>[];
  const timeline = (own.length ? own.map(t => timelineView(t, bedId, deviceId)) : related.map(a => {
    const v = actionView(a);
    return {ts: a.occurred_at, who: v.who, what: v.what, why: v.why, kind: a.mode === 'automatic' ? 'agent' : 'staff', raw: a};
  })).map(t => ({...t, before: t.ts < attackStart})).sort((a, b) => a.ts - b.ts);
  const firstDuring = timeline.findIndex(t => !t.before);
  const allowed = can(role, 'security');
  const affected = Array.isArray(d.affected_beds) ? d.affected_beds.map(String) : bedId ? [bedId] : [];
  return <div className="page pages-page incident-page">
    <PageHeader title={title(d)} description={`Opened ${dateTime(inc.data.ts)} by ${actorName(inc.data.by)}. Follow the response and review the evidence.`}>
      <Link className="button-link" to={`/incident/${encodeURIComponent(inc.data.record_id)}/report`}><FileText size={16} aria-hidden="true" />CERT-In report draft</Link>
    </PageHeader>
    <ResourceState loading={false} error={inc.error} retry={() => void inc.reload()} />
    <Stats items={[
      {label: 'Status', value: <span className="stat-word">{status.replace(/_/g, ' ')}</span>, hint: 'The current stage of the investigation.'},
      {label: 'Opened', value: time(inc.data.ts, true), hint: 'When the evidence agent opened this incident.'},
      {label: 'Report clock', value: countdown(due, now), hint: 'Time left until the incident reporting deadline.', sub: `due ${time(due, true)}${report ? ' · from report draft' : ' · 6 h from detection'}`},
      {label: 'Evidence files', value: evidence.length, hint: 'Files kept with a SHA-256 fingerprint.'},
    ]} />
    <div className="row-actions incident-controls">
      <Button disabled={!allowed || closed} pending={capture.pending} onClick={() => void capture.run(`/api/incidents/${encodeURIComponent(inc.data!.record_id)}/evidence`, {type: 'capture_evidence', bedId})}><Camera size={16} aria-hidden="true" />Capture evidence</Button>
      <Button disabled={!allowed || closed || contain.pending} onClick={() => setContaining(true)}><Lock size={16} aria-hidden="true" />Contain</Button>
      <Button variant="danger" disabled={!allowed || closed || resolve.pending} onClick={() => setClosing(true)}><CheckCircle2 size={16} aria-hidden="true" />Close incident</Button>
      {closed && <span className="tiny muted">This incident is closed. Its records remain available.</span>}
    </div>
    <Feedback message={capture.feedback || contain.feedback || resolve.feedback} failed={capture.failed || contain.failed || resolve.failed} />
    <div className="incident-layout">
      <Panel title="Timeline" caption="Who acted, what changed, and when. Details keep every original event.">
        {!timeline.length ? <Empty title="No events recorded yet" detail="The evidence agent will add the sequence of events here." /> : <ol className="timeline pages-timeline">
          {timeline.flatMap((t, i) => [
            ...(i === firstDuring && firstDuring > 0 ? [<li key="divider" className="tl-divider">Attack starts · {time(attackStart, true)}</li>] : []),
            <li key={`${t.ts}-${i}`} className={`tl-${t.kind} ${t.before ? 'tl-before' : ''}`}>
              <time className="mono">{time(t.ts, true)}</time><div><strong>{t.what}</strong><p className="tiny">{t.who}{t.before ? ' · before the attack' : ''}</p>{t.why && <p className="tiny timeline-why">{t.why}</p>}
                <details className="record-details"><summary>Details</summary><div className="record-original"><pre>{JSON.stringify(t.raw, null, 2)}</pre></div></details>
              </div>
            </li>,
          ])}
        </ol>}
      </Panel>
      <Panel title="Evidence" caption="Each SHA-256 fingerprint can be copied and compared with the original file.">
        {!evidence.length ? <Empty title="No evidence captured yet" detail="The evidence agent keeps signal and network records when it opens an incident." /> :
          <ul className="evidence-list">{evidence.map((e, i) => <EvidenceRecord key={String(e.evidence_id ?? e.sha256 ?? i)} e={e} incidentId={inc.data!.record_id} />)}</ul>}
        {Array.isArray(d.missing_context) && d.missing_context.length > 0 && <p className="tiny muted">Context still needed: {d.missing_context.map(x => plainText(String(x).replace(/_/g, ' '))).join(', ')}</p>}
        {d.pcap_available === false && <p className="tiny muted">No packet capture is available. The accepted messages are kept as evidence.</p>}
      </Panel>
    </div>
    <div className="incident-layout incident-bottom">
      <Panel title="Affected beds" caption="Check patients by hand while their monitor signals cannot be trusted."><div className="chips">{affected.length ? affected.map(b => <BedLink key={b} id={b} />) : <span className="tiny muted">No beds recorded</span>}</div></Panel>
      <Panel title="Actions taken" caption="Reversible actions can be undone by IT security."><ActionFeed actions={related.slice(0, 8)} /></Panel>
    </div>
    <ConfirmDialog open={containing} title="Contain this incident?" bed={bedId} monitor={deviceId} consequence="The agents will keep this monitor cut off from the ward. Check the patient by hand while IT investigates." actionLabel="Contain incident" pending={contain.pending} onClose={() => setContaining(false)} onConfirm={() => {setContaining(false); void contain.run(`/api/incidents/${encodeURIComponent(inc.data!.record_id)}/contain`, {type: 'contain_incident', bedId});}} />
    <Dialog open={closing} title="Close this incident?" onClose={() => setClosing(false)} actions={<>
      <Button variant="ghost" onClick={() => setClosing(false)}>Cancel</Button><Button variant="danger" pending={resolve.pending} disabled={!reason.trim()}
        onClick={() => {setClosing(false); void resolve.run(`/api/incidents/${encodeURIComponent(inc.data!.record_id)}/resolve`, {type: 'resolve_incident', bedId, reason: reason.trim()});}}>Close incident</Button>
    </>}><p>Record why the investigation is finished. The timeline and evidence remain in the audit record.</p><label className="field">Reason<textarea value={reason} onChange={e => setReason(e.target.value)} maxLength={400} rows={3} placeholder="For example, monitor reflashed and verified" /></label></Dialog>
  </div>;
}
