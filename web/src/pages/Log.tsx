import {useMemo, useState} from 'react';
import {Search, Bot, User} from 'lucide-react';
import {useWard} from '../lib/store';
import {dateTime, staff} from '../lib/domain';
import {Empty, PageTitle, Panel, Tip, Undo} from '../components/ui';
import {Tabs} from '../components/extra';

const AGENTS: Record<string, string> = {
  A1: 'Alert agent', A2: 'Network cut-off agent', A3: 'Evidence agent', A4: 'Fleet agent',
  A5: 'Report agent', A6: 'Ticket agent', A7: 'Workload agent', A8: 'Briefing agent',
};

export function LogPage() {
  const actions = useWard(s => s.actions);
  const [mode, setMode] = useState<'all' | 'automatic' | 'person'>('all');
  const [q, setQ] = useState('');
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return actions.filter(a => (mode === 'all' || a.mode === mode) &&
      (!needle || [a.action, a.actor, a.action_code, a.bed_id, a.device_id, a.approved_by].some(x => x?.toLowerCase().includes(needle))));
  }, [actions, mode, q]);
  return (
    <div className="page">
      <PageTitle eyebrow="S11 · Audit" title="Action log"
                 description="Every automatic and staff action, who or what did it, and its undo. Newest first, last 200 actions.">
        <Tabs label="Who acted" value={mode} onChange={setMode} options={[
          {value: 'all', label: 'All', hint: 'Agents and people.', count: actions.length},
          {value: 'automatic', label: 'Automatic', hint: 'Actions taken by an agent on its own.', count: actions.filter(a => a.mode === 'automatic').length},
          {value: 'person', label: 'Staff', hint: 'Actions taken by a signed-in person.', count: actions.filter(a => a.mode === 'person').length},
        ]} />
      </PageTitle>
      <Panel title={`${shown.length} action${shown.length === 1 ? '' : 's'}`} caption="Undo asks the responsible agent to reverse the action; the reversal is logged too."
             aside={<label className="search"><Search size={14} aria-hidden="true" /><span className="sr-only">Search actions</span>
               <input type="search" placeholder="Search bed, device, agent, action" value={q} onChange={e => setQ(e.target.value)} /></label>}>
        {shown.length === 0 ? <Empty title="No matching actions" detail={actions.length ? 'Try a different search or filter.' : 'Actions appear here as soon as agents or staff act.'} /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                <th scope="col">Time</th>
                <th scope="col"><Tip text="The agent (A1–A8) or the person who acted."><span>Agent or person</span></Tip></th>
                <th scope="col">Action</th><th scope="col">Bed / device</th>
                <th scope="col"><Tip text="Person who approved the action, when approval was needed."><span>Approved by</span></Tip></th>
                <th scope="col"><Tip text="Shown only on actions the API marks as reversible (e.g. a cut-off). IT security can undo."><span>Undo</span></Tip></th>
              </tr></thead>
              <tbody>
                {shown.map(a => (
                  <tr key={a.id}>
                    <td className="mono nowrap">{dateTime(a.occurred_at)}</td>
                    <td className="nowrap">{a.mode === 'automatic' ? <Bot size={13} aria-hidden="true" /> : <User size={13} aria-hidden="true" />}{' '}
                      {AGENTS[a.actor] ? <Tip text={AGENTS[a.actor]}><span>{a.actor}</span></Tip> : staff(a.actor)}</td>
                    <td><span className="what">{a.action}</span><span className="tiny mono"> · {a.action_code}</span>
                      {a.references_action_id && <span className="tiny"> · reverses {a.references_action_id.slice(0, 12)}</span>}</td>
                    <td className="mono">{a.bed_id ?? a.device_id ?? 'Ward'}</td>
                    <td>{a.approved_by ? staff(a.approved_by) : '—'}</td>
                    <td>{a.mode === 'automatic' && a.undoable ? <Undo action={a} /> : <Tip text={a.mode === 'automatic' ? 'This automatic action has no reversal (e.g. a message sent, a briefing written).' : 'Staff actions are not undone from here.'}><span className="tiny">—</span></Tip>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
