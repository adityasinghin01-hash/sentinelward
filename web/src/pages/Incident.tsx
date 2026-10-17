import {useState} from 'react';
import {Link, useParams} from 'react-router-dom';
import {Camera, Download, FileText, Fingerprint, Lock, ShieldAlert, CheckCircle2} from 'lucide-react';
import {useWard} from '../lib/store';
import {useCommand, useNow, useResource} from '../lib/hooks';
import {bytes, can, certDeadline, countdown, dateTime, downloadName, evidenceView, staff, time, timelineRow} from '../lib/domain';
import {downloadJson} from '../lib/api';
import type {AgentRecord} from '../lib/types';
import {ActionList, BedLink, Empty, Feedback, PageTitle, Panel, ResourceState, Stats, Tip, humanText, humanName} from '../components/ui';
import {Chip, Dialog} from '../components/extra';

type Evidence = Record<string, unknown>;
type Row = {ts: number; what: string; who: string; kind: 'agent' | 'staff' | 'verdict'; before: boolean};
const title = (d: Record<string, unknown>) =>
  `${String(d.attack_type ?? d.title ?? 'Suspected attack').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())} on ${String(d.device_id ?? 'a monitor')}, Bed ${String(d.bed_id ?? '—')}`;

export function IncidentListPage() {
  const list = useResource<AgentRecord[]>('/api/incidents', 8000);
  const rows = list.data ?? [];
  return (
    <div className="page">
      <PageTitle eyebrow="S7 · Incidents" title="Incidents" description="Every security incident the evidence agent (A3) has opened, newest first." />
      <ResourceState loading={list.loading && !rows.length} error={list.error} retry={() => void list.reload()} />
      <Panel title={`${rows.length} incident${rows.length === 1 ? '' : 's'}`}>
        {rows.length === 0 && !list.loading ? (
          <Empty title="No incidents recorded" detail="When a monitor looks attacked, A3 freezes the evidence and opens an incident here.">
            <Link to="/security" className="button-link">Back to Security</Link>
          </Empty>
        ) : (
          <ul className="incident-list">
            {rows.map(r => (
              <li key={r.record_id}>
                <ShieldAlert size={15} aria-hidden="true" />
                <div>
                  <Link className="inline-link" to={`/incident/${encodeURIComponent(r.record_id)}`}>{title(r.data)}</Link>
                  <p className="tiny">{String(r.data.status ?? 'open').replace(/_/g, ' ')} · {dateTime(r.ts)} <Tip text={`Incident identifier: ${r.record_id}`}><span className="tiny"> · Record</span></Tip></p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function EvidenceItem({e, incidentId}: {e: Evidence; incidentId: string}) {
  const sha = typeof e.sha256 === 'string' ? e.sha256 : '';
  const view = evidenceView(e);
  const name = view.file || 'evidence';
  const hasContent = e.content !== undefined;
  return (
    <li className="evidence">
      <div className="evidence-head">
        <FileText size={15} aria-hidden="true" />
        <strong>{view.title}</strong>
        {e.verified === true && <Chip kind="info" hint="The agent re-read the file and its fingerprint matched."><CheckCircle2 size={12} aria-hidden="true" />verified</Chip>}
        {e.available === false && <Chip kind="striped" hint="This file was expected but no data was available for it.">no data</Chip>}
      </div>
      <p className="tiny">{view.file && view.file !== view.title ? `${view.file} · ` : ''}{view.size === null ? 'size not recorded' : bytes(view.size)}{e.captured_at ? ` · ${time(Number(e.captured_at), true)}` : ''}{e.captured_by ? ` · ${staff(e.captured_by)}` : ''}</p>
      <Tip text="SHA-256 fingerprint of the file. Any change to the file changes this value, so it proves the evidence was not altered.">
        <code className="sha"><Fingerprint size={12} aria-hidden="true" /> {sha ? `${sha.slice(0, 16)}…${sha.slice(-8)}` : 'no fingerprint'}</code>
      </Tip>
      {typeof e.source === 'string' && <p className="tiny">Source: {e.source}</p>}
      <button className="button-small ghost" onClick={() => downloadJson(downloadName(incidentId, name), hasContent ? e.content : e)}
              title={hasContent ? 'Download the captured evidence content as JSON.' : 'The file itself stays on the server; download its record (path, size, fingerprint).'}>
        <Download size={13} aria-hidden="true" /> {hasContent ? 'Download' : 'Download record'}
      </button>
    </li>
  );
}

export function IncidentPage() {
  const {incidentId = ''} = useParams();
  const role = useWard(s => s.session?.role);
  const actions = useWard(s => s.actions);
  const now = useNow();
  const inc = useResource<AgentRecord>(`/api/incidents/${encodeURIComponent(incidentId)}`, 5000);
  const reports = useResource<AgentRecord[]>('/api/reports', 10000);
  const rep = {data: reports.data?.find(r => r.data.incident_id === incidentId || r.record_id === incidentId) ?? null};
  const capture = useCommand();
  const contain = useCommand();
  const resolve = useCommand();
  const [closing, setClosing] = useState(false);
  const [reason, setReason] = useState('');

  if (!inc.data) {
    if (inc.error && !inc.loading) return (
      <div className="page"><Empty title="Incident not found" detail={inc.error}><Link to="/security" className="button-link">Back to Security</Link></Empty></div>
    );
    return <div className="page"><div className="skeleton-block" aria-busy="true">Loading incident…</div></div>;
  }
  const d = inc.data.data;
  const bedId = String(d.bed_id ?? '');
  const deviceId = String(d.device_id ?? '');
  const status = String(d.status ?? 'open');
  const closed = ['resolved', 'closed'].includes(status);
  const evidence = (Array.isArray(d.evidence) ? d.evidence : []) as Evidence[];
  const due = certDeadline(rep.data, inc.data) ?? inc.data.ts + 6 * 3600_000;
  const fromReport = !!rep.data;
  const attackStart = Number(d.attack_start_ts ?? d.detected_ts) || inc.data.ts;
  const related = actions.filter(a => (bedId && a.bed_id === bedId) || (deviceId && a.device_id === deviceId)).filter(a => a.occurred_at >= inc.data!.ts - 60_000);
  // A3's own timeline when it has one (it already includes the agents' actions); else the related actions.
  const own = ((Array.isArray(d.timeline) ? d.timeline : []) as Record<string, unknown>[]).map(timelineRow);
  const timeline: Row[] = (own.length
    ? own.map(t => ({...t, kind: /^A[1-8]$/.test(t.who) ? 'agent' as const : t.who === 'Staff' ? 'staff' as const : 'verdict' as const, before: t.ts < attackStart}))
    : related.map(a => ({ts: a.occurred_at, kind: a.mode === 'automatic' ? 'agent' as const : 'staff' as const, who: a.actor.startsWith('staff:') ? staff(a.actor) : a.actor, what: a.action, before: a.occurred_at < attackStart})))
    .sort((a, b) => a.ts - b.ts);
  const firstDuring = timeline.findIndex(t => !t.before);
  const allowed = can(role, 'security');
  const affected = Array.isArray(d.affected_beds) ? d.affected_beds.map(String) : bedId ? [bedId] : [];
  return (
    <div className="page">
      <PageTitle eyebrow={`S7 · Incident ${inc.data.record_id}`} title={title(d)}
                 description={`Opened ${dateTime(inc.data.ts)} by ${humanName(inc.data.by)}. Minute by minute, with fingerprinted evidence.`}>
        <Link className="button-link" to={`/incident/${encodeURIComponent(inc.data.record_id)}/report`} title="Open the CERT-In report draft for a person to check and send.">
          <FileText size={14} aria-hidden="true" /> CERT-In report draft
        </Link>
      </PageTitle>
      <Stats items={[
        {label: 'Status', value: <span className="stat-word">{status.replace(/_/g, ' ')}</span>, hint: 'Where this incident stands: pending, evidence verified, contained, resolved.'},
        {label: 'Started', value: time(inc.data.ts, true), hint: 'When the first suspicious verdict for this device arrived.'},
        {label: 'CERT-In clock', value: countdown(due, now), hint: 'CERT-In asks for a report within 6 hours of noticing an incident. Same deadline as the report draft screen.', sub: fromReport ? `due ${time(due, true)} · from the report draft` : `due ${time(due, true)} · 6 h from detection`},
        {label: 'Evidence files', value: evidence.length, hint: 'Files frozen for this incident, each with a SHA-256 fingerprint.'},
      ]} />
      <div className="row-actions">
        <button disabled={!allowed || closed || capture.pending} title={allowed ? 'Freeze a new snapshot of the bed, verdict, scores and network now.' : 'Only IT security can capture evidence.'}
                onClick={() => void capture.run(`/api/incidents/${encodeURIComponent(inc.data!.record_id)}/evidence`, {type: 'capture_evidence', bedId})}>
          <Camera size={14} aria-hidden="true" /> Capture evidence
        </button>
        <button disabled={!allowed || closed || contain.pending} title={allowed ? 'Ask the agents to contain this incident (keep the device cut off).' : 'Only IT security can contain incidents.'}
                onClick={() => void contain.run(`/api/incidents/${encodeURIComponent(inc.data!.record_id)}/contain`, {type: 'contain_incident', bedId})}>
          <Lock size={14} aria-hidden="true" /> Contain
        </button>
        <button className="danger-outline" disabled={!allowed || closed || resolve.pending} title={allowed ? 'Close this incident. You will be asked for a reason.' : 'Only IT security can close incidents.'}
                onClick={() => setClosing(true)}>
          <CheckCircle2 size={14} aria-hidden="true" /> Close incident
        </button>
      </div>
      <Feedback message={capture.feedback || contain.feedback || resolve.feedback} failed={capture.failed || contain.failed || resolve.failed} />
      <div className="incident-layout">
        <Panel title="Timeline" caption="Each event with its time and which agent or person did it.">
          {timeline.length === 0 ? <p className="tiny">No events recorded yet.</p> : (
            <ol className="timeline">
              {timeline.flatMap((t, i) => [
                ...(i === firstDuring && firstDuring > 0 ? [<li key="divider" className="tl-divider">ATTACK STARTS · {time(attackStart, true)}</li>] : []),
                <li key={`${t.ts}-${i}`} className={`tl-${t.kind} ${t.before ? 'tl-before' : ''}`} title={t.before ? 'Before the attack started: context only.' : undefined}>
                  <time className="mono">{time(t.ts, true)}</time>
                  <div><strong title={t.what}>{humanText(t.what)}</strong><p className="tiny">{humanName(t.who)}{t.before ? ' · before the attack' : ''}</p></div>
                </li>,
              ])}
            </ol>
          )}
        </Panel>
        <Panel title="Evidence" caption="Fingerprinted files ready for the report. A changed file would no longer match its fingerprint.">
          {evidence.length === 0 ? <Empty title="No evidence frozen yet" detail="A3 freezes the readings, network log and verdict log as soon as it opens the incident." /> : (
            <ul className="evidence-list">{evidence.map((e, i) => <EvidenceItem key={String(e.evidence_id ?? e.sha256 ?? i)} e={e} incidentId={inc.data!.record_id} />)}</ul>
          )}
          {Array.isArray(d.missing_context) && d.missing_context.length > 0 && (
            <p className="tiny">Missing context: {d.missing_context.map(String).join(', ')}</p>
          )}
          {d.pcap_available === false && <p className="tiny">No packet capture: evidence is the accepted message transcript.</p>}
        </Panel>
      </div>
      <div className="incident-layout">
        <Panel title="Affected beds" caption="The clinical side: nurses see these beds as untrusted and check by hand.">
          <div className="chips">{affected.length ? affected.map(b => <BedLink key={b} id={b} />) : <span className="tiny">None recorded</span>}</div>
        </Panel>
        <Panel title="Actions taken" caption="Automatic actions show Undo (IT security).">
          <ActionList actions={related.slice(0, 12)} />
        </Panel>
      </div>
      <Dialog open={closing} title="Close this incident?" onClose={() => setClosing(false)} actions={<>
        <button className="ghost" onClick={() => setClosing(false)}>Cancel</button>
        <button className="danger" disabled={!reason.trim()} title={reason.trim() ? 'Ask the agents to resolve this incident with your reason.' : 'Enter a reason first.'}
                onClick={() => { setClosing(false); void resolve.run(`/api/incidents/${encodeURIComponent(inc.data!.record_id)}/resolve`, {type: 'resolve_incident', bedId, reason: reason.trim()}); }}>
          Close incident</button></>}>
        <label className="field">Reason (kept in the audit log)
          <textarea value={reason} onChange={e => setReason(e.target.value)} maxLength={400} rows={3} placeholder="e.g. monitor reflashed and verified" />
        </label>
      </Dialog>
    </div>
  );
}
