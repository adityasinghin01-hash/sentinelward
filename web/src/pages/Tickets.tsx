import {useState} from 'react';
import type {FormEvent} from 'react';
import {Plus, Wrench, CheckCircle2, Play} from 'lucide-react';
import {useWard} from '../lib/store';
import {useCommand, useResource} from '../lib/hooks';
import {can, dateTime, ticketColumn} from '../lib/domain';
import type {AgentRecord} from '../lib/types';
import {Button, Empty, Feedback, Panel, ResourceState, Tip} from '../components/ui';
import {PageHeader} from '../components/pages/PageHeader';
import {actorName, plainText} from '../components/pages/actions';
import {Chip} from '../components/extra';

const COLUMNS = [
  {key: 'new', title: 'New', hint: 'Opened by the ticket agent (A6) or a person; nobody has taken it yet.'},
  {key: 'progress', title: 'In progress', hint: 'A biomedical engineer has taken this job.'},
  {key: 'done', title: 'Done', hint: 'Fixed and closed.'},
] as const;

function problem(d: Record<string, unknown>) {
  if (typeof d.issue === 'string' && d.issue) return plainText(d.issue);
  const kinds = Array.isArray(d.fault_types) ? d.fault_types.map(String) : [];
  if (kinds.includes('DRIFTING')) return 'Blood-pressure line drifting away from the cuff reading.';
  if (kinds.includes('LOOSE_SENSOR')) return `Finger sensor came loose${typeof d.loose_episodes_30m === 'number' ? ` ${d.loose_episodes_30m} times in 30 min` : ''}.`;
  return plainText(kinds.join(', ').replace(/_/g, ' ')) || 'Problem not described';
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
        <Chip hint="Who opened this ticket.">{actorName(String(d.created_by ?? t.by))}</Chip>
      </div>
      <p className="ticket-problem">{problem(d)}</p>
      {typeof (d.suggested_fix ?? d.suggestion) === 'string' && <p className="tiny"><strong>Suggested fix:</strong> {plainText(String(d.suggested_fix ?? d.suggestion))}</p>}
      <p className="tiny">
        {typeof d.issues_30d === 'number' && <><Tip text="How many separate faults this device had in the last 30 days. Repeats suggest replacing it."><span>Issues (30 days): <span className="mono">{d.issues_30d}</span></span></Tip>{' · '}</>}
        {typeof d.issues_30d !== 'number' && typeof d.count === 'number' && <><Tip text="How many times the ticket agent (A6) saw this fault on this ticket. A 30-day history is not available."><span>Seen <span className="mono">{d.count}</span>×</span></Tip>{' · '}</>}
        opened {dateTime(Number(d.first_seen_ts ?? d.first_ts ?? d.created_at ?? t.ts))}
      </p>
      {typeof d.note === 'string' && d.note && <p className="tiny">Note: {plainText(d.note)}</p>}
      <div className="row-actions">
        {col === 'new' && <Button size={36} disabled={!edit || cmd.pending} onClick={() => update('assigned')}
                                  title={edit ? 'Take this job: moves it to In progress.' : 'Only biomedical engineers update tickets.'}><Play size={13} aria-hidden="true" /> Start</Button>}
        {col !== 'done' && <Button size={36} disabled={!edit || cmd.pending} onClick={() => update('resolved')}
                                   title={edit ? 'Mark the device fixed: moves it to Done.' : 'Only biomedical engineers update tickets.'}><CheckCircle2 size={13} aria-hidden="true" /> Resolve</Button>}
      </div>
      <Feedback message={cmd.feedback} failed={cmd.failed} />
      <details className="record-details"><summary>Ticket record</summary><div className="record-original"><pre>{JSON.stringify(t, null, 2)}</pre></div></details>
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
    <div className="page pages-page tickets-page">
      <PageHeader title="Repair tickets" description="Sensor and monitor repairs, from the first report to a verified fix." />
      <ResourceState loading={tickets.loading && !list.length} error={tickets.error} retry={() => void tickets.reload()} />
      <div className="tickets-layout">
        <div className="tickets-board-wrap"><div className="tickets-board-heading"><h2>{tickets.data ? `${list.filter(t => ticketColumn(t.data.status) !== 'done').length} open jobs` : 'Repair jobs'}</h2><p>Biomedical engineers use Start and Resolve to move a job.</p></div><div className="board">
          {COLUMNS.map(c => {
            const items = list.filter(t => ticketColumn(t.data.status) === c.key);
            return (
              <section key={c.key} className="column" aria-label={`${c.title} tickets`}>
                <h2><Tip text={c.hint}><span>{c.title}</span></Tip> <span className="tab-count mono">{items.length}</span></h2>
                {items.length === 0 && tickets.data ? <p className="tiny column-empty">{tickets.loading ? 'Loading repair jobs…' : c.key === 'new' ? 'No new repair jobs' : c.key === 'progress' ? 'No repairs in progress' : 'No completed repairs yet'}</p> : (
                  <ul className="ticket-list">{items.map(t => <TicketCard key={t.record_id} t={t} />)}</ul>
                )}
              </section>
            );
          })}
        </div></div>
        <aside>
          <Panel title="Devices with repeat problems" caption="Two or more issues: consider replacing rather than refitting.">
            {repeat.length === 0 && tickets.data ? <Empty title="No repeat problems recorded" detail="No monitor has two or more recorded issues." /> : (
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
              <p className="tiny muted ticket-form-hint">Choose a bed and describe the problem to open a ticket.</p>
              <Button type="submit" pending={create.pending} disabled={!bed || !issue.trim()} title="Open a new ticket in the New column.">
                <Plus size={14} aria-hidden="true" /> Open ticket
              </Button>
            </form>
            <Feedback message={create.feedback} failed={create.failed} />
          </Panel>
        </aside>
      </div>
    </div>
  );
}
