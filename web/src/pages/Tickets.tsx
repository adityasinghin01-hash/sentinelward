import {useState} from 'react';
import type {FormEvent} from 'react';
import {Plus, Wrench, CheckCircle2, Play} from 'lucide-react';
import {useWard} from '../lib/store';
import {useCommand, useResource} from '../lib/hooks';
import {can, dateTime, staff, ticketColumn} from '../lib/domain';
import type {AgentRecord} from '../lib/types';
import {Empty, Feedback, PageTitle, Panel, ResourceState, Tip} from '../components/ui';
import {Chip} from '../components/extra';

const COLUMNS = [
  {key: 'new', title: 'New', hint: 'Opened by the ticket agent (A6) or a person; nobody has taken it yet.'},
  {key: 'progress', title: 'In progress', hint: 'A biomedical engineer has taken this job.'},
  {key: 'done', title: 'Done', hint: 'Fixed and closed.'},
] as const;

function problem(d: Record<string, unknown>) {
  if (typeof d.issue === 'string' && d.issue) return d.issue;
  const kinds = Array.isArray(d.fault_types) ? d.fault_types.map(String) : [];
  if (kinds.includes('DRIFTING')) return 'Blood-pressure line drifting away from the cuff reading.';
  if (kinds.includes('LOOSE_SENSOR')) return `Finger sensor came loose${typeof d.loose_episodes_30m === 'number' ? ` ${d.loose_episodes_30m} times in 30 min` : ''}.`;
  return kinds.join(', ') || 'Problem not described';
}

function TicketCard({t}: {t: AgentRecord}) {
  const role = useWard(s => s.session?.role);
  const cmd = useCommand();
  const d = t.data;
  const col = ticketColumn(d.status);
  const edit = can(role, 'ticketEdit');
  const update = (status: 'assigned' | 'resolved') =>
    void cmd.run(`/api/tickets/${encodeURIComponent(t.record_id)}`, {type: 'update_ticket', ticketId: t.record_id, status}, 'PATCH');
  return (
    <li className="ticket">
      <div className="ticket-head">
        <Wrench size={14} aria-hidden="true" />
        <strong className="mono">{String(d.device_id ?? '—')}</strong>
        <span className="muted">Bed {String(d.bed_id ?? '—')}</span>
        <Chip hint="Who opened this ticket.">{t.by === 'A6' ? 'A6 agent' : staff(d.created_by ?? t.by)}</Chip>
      </div>
      <p className="ticket-problem">{problem(d)}</p>
      {typeof d.suggestion === 'string' && <p className="tiny"><strong>Suggested fix:</strong> {d.suggestion}</p>}
      <p className="tiny">
        <Tip text="How many separate faults this device had in the last 30 days. Repeats suggest replacing it."><span>Issues (30 days): <span className="mono">{typeof d.issues_30d === 'number' ? d.issues_30d : '—'}</span></span></Tip>
        {' · '}opened {dateTime(Number(d.first_ts ?? d.created_at ?? t.ts))}
      </p>
      {typeof d.note === 'string' && d.note && <p className="tiny">Note: {d.note}</p>}
      <div className="row-actions">
        {col === 'new' && <button className="button-small" disabled={!edit || cmd.pending} onClick={() => update('assigned')}
                                  title={edit ? 'Take this job: moves it to In progress.' : 'Only biomedical engineers update tickets.'}><Play size={13} aria-hidden="true" /> Start</button>}
        {col !== 'done' && <button className="button-small" disabled={!edit || cmd.pending} onClick={() => update('resolved')}
                                   title={edit ? 'Mark the device fixed: moves it to Done.' : 'Only biomedical engineers update tickets.'}><CheckCircle2 size={13} aria-hidden="true" /> Resolve</button>}
      </div>
      <Feedback message={cmd.feedback} failed={cmd.failed} />
    </li>
  );
}

export function TicketsPage() {
  const tickets = useResource<AgentRecord[]>('/api/tickets', 6000);
  const beds = useWard(s => s.beds);
  const create = useCommand();
  const [bed, setBed] = useState('');
  const [issue, setIssue] = useState('');
  const list = tickets.data ?? [];
  // Issues per device: the larger of its ticket count and the agent's 30-day issue counter.
  const issues = new Map<string, {tickets: number; counter: number}>();
  for (const t of list) {
    const k = String(t.data.device_id ?? '—');
    const cur = issues.get(k) ?? {tickets: 0, counter: 0};
    issues.set(k, {tickets: cur.tickets + 1, counter: Math.max(cur.counter, Number(t.data.issues_30d) || 0)});
  }
  const repeat = [...issues].map(([device, c]) => ({device, n: Math.max(c.tickets, c.counter)})).filter(r => r.n >= 2).sort((a, b) => b.n - a.n);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (await create.run('/api/tickets', {type: 'create_ticket', bedId: bed, issue: issue.trim()})) setIssue('');
  };
  return (
    <div className="page">
      <PageTitle eyebrow="S9 · Biomedical engineering" title="Repair tickets"
                 description="Sensor and device jobs from loose and drifting verdicts (agent A6), plus jobs staff report by hand." />
      <ResourceState loading={tickets.loading && !list.length} error={tickets.error} retry={() => void tickets.reload()} />
      <div className="tickets-layout">
        <div className="board">
          {COLUMNS.map(c => {
            const items = list.filter(t => ticketColumn(t.data.status) === c.key);
            return (
              <section key={c.key} className="column" aria-label={`${c.title} tickets`}>
                <h2><Tip text={c.hint}><span>{c.title}</span></Tip> <span className="tab-count mono">{items.length}</span></h2>
                {items.length === 0 ? <p className="tiny column-empty">{c.key === 'new' ? 'No new jobs. Sensors are behaving.' : 'Nothing here.'}</p> : (
                  <ul className="ticket-list">{items.map(t => <TicketCard key={t.record_id} t={t} />)}</ul>
                )}
              </section>
            );
          })}
        </div>
        <aside>
          <Panel title="Devices with repeat problems" caption="Two or more issues: consider replacing rather than refitting.">
            {repeat.length === 0 ? <Empty title="No repeat offenders" detail="No device has had more than one issue." /> : (
              <ul className="plain-list">{repeat.map(r => <li key={r.device}><span className="mono">{r.device}</span><span className="mono">{r.n} issues</span></li>)}</ul>
            )}
          </Panel>
          <Panel title="Report a problem" caption="Any role can open a ticket for a bed's monitor.">
            <form className="stack" onSubmit={e => void submit(e)}>
              <label className="field">Bed
                <select value={bed} onChange={e => setBed(e.target.value)} required>
                  <option value="">Choose a bed</option>
                  {(beds.length ? beds.map(b => b.bed_id) : Array.from({length: 12}, (_, i) => `B${String(i + 1).padStart(2, '0')}`)).map(id => <option key={id} value={id}>{id}</option>)}
                </select>
              </label>
              <label className="field">What is wrong
                <textarea rows={3} value={issue} maxLength={2000} onChange={e => setIssue(e.target.value)} placeholder="e.g. SpO2 clip cracked, keeps falling off" required />
              </label>
              <button type="submit" disabled={!bed || !issue.trim() || create.pending} title="Open a new ticket in the New column.">
                <Plus size={14} aria-hidden="true" /> Open ticket
              </button>
            </form>
            <Feedback message={create.feedback} failed={create.failed} />
          </Panel>
        </aside>
      </div>
    </div>
  );
}
