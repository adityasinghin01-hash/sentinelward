import {Fragment, useMemo, useState} from 'react';
import {Search} from 'lucide-react';
import {useWard} from '../lib/store';
import {time} from '../lib/domain';
import {Button, Empty, Panel, ResourceState, SegmentedControl} from '../components/ui';
import {PageHeader} from '../components/pages/PageHeader';
import {ActorIcon, UndoAction} from '../components/pages/ActionRecord';
import {actionView} from '../components/pages/actions';
import type {ActorKind} from '../components/pages/actions';

type Filter = 'all' | ActorKind;
export function LogPage() {
  const actions = useWard(s => s.actions);
  const error = useWard(s => s.error);
  const receivedAt = useWard(s => s.receivedAt);
  const [mode, setMode] = useState<Filter>('all');
  const [q, setQ] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const loading = !receivedAt && !actions.length && !error;
  const rows = useMemo(() => actions.map(a => ({a, v: actionView(a)})).sort((a, b) => b.a.occurred_at - a.a.occurred_at), [actions]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter(({a, v}) => (mode === 'all' || v.kind === mode) &&
      (!needle || [...Object.values(v), a.action, a.actor, a.action_code, a.bed_id, a.device_id, a.approved_by].some(x => x?.toLowerCase().includes(needle))));
  }, [rows, mode, q]);
  return <div className="page pages-page log-page">
    <PageHeader title="Action log" description="Who acted, what changed, and why. Newest first · up to 200 actions.">
      <SegmentedControl label="Who acted" value={mode} onChange={setMode} options={[
        {value: 'all', label: 'All'}, {value: 'people', label: 'People'}, {value: 'agents', label: 'Agents'}, {value: 'it', label: 'IT'},
      ]} />
    </PageHeader>
    <ResourceState loading={loading} error={error || ''} />
    <Panel title={!receivedAt && !actions.length ? 'Actions' : `${shown.length} action${shown.length === 1 ? '' : 's'}`} caption="Every row has an original record in Details. IT can undo reversible actions."
      aside={<label className="search pages-search"><Search size={16} aria-hidden="true" /><span className="sr-only">Search actions</span>
        <input type="search" placeholder="Search actions, names or beds" value={q} onChange={e => setQ(e.target.value)} /></label>}>
      {!shown.length && !loading ? <Empty title={q || mode !== 'all' ? 'No matching actions' : 'No actions recorded yet'} detail={q || mode !== 'all' ? 'Try another name, bed or filter.' : 'Actions appear when agents or staff respond to the ward.'} /> : shown.length > 0 ?
        <div className="table-wrap log-table-wrap"><table className="table log-table">
          <thead><tr><th scope="col">When</th><th scope="col">Who</th><th scope="col">Did what</th><th scope="col">Bed</th><th scope="col">Why</th><th scope="col">Record</th><th scope="col"><span className="sr-only">Undo</span></th></tr></thead>
          <tbody>{shown.map(({a, v}, i) => {
            const minute = Math.floor(a.occurred_at / 60_000);
            const group = i === 0 || Math.floor(shown[i - 1].a.occurred_at / 60_000) !== minute;
            return <Fragment key={a.id}>
              {group && <tr className="log-minute"><th colSpan={7} scope="rowgroup"><time dateTime={new Date(a.occurred_at).toISOString()}>{new Date(a.occurred_at).toLocaleDateString('en-GB', {day: '2-digit', month: 'short'})} · {time(a.occurred_at)}</time></th></tr>}
              <tr><td className="mono log-time"><time dateTime={new Date(a.occurred_at).toISOString()}>{time(a.occurred_at, true)}</time></td>
                <td><span className="log-actor"><ActorIcon kind={v.kind} />{v.who}</span></td>
                <td className="log-what"><span className="event-summary" title={v.summary}>{v.summary}</span>{a.references_action_id && <span className="tiny muted"> · reversal</span>}</td>
                <td className="mono nowrap">{v.bed}</td><td className="log-why">{v.why}</td>
                <td><Button size={36} variant="ghost" aria-expanded={expanded.has(a.id)} aria-controls={expanded.has(a.id) ? `record-${a.id}` : undefined} onClick={() => setExpanded(old => {const next = new Set(old); if (next.has(a.id)) next.delete(a.id); else next.add(a.id); return next;})}>Details</Button></td>
                <td>{a.mode === 'automatic' && a.undoable && <UndoAction action={a} />}</td>
              </tr>
              {expanded.has(a.id) && <tr className="log-details" id={`record-${a.id}`}><td colSpan={7}><div className="record-original"><p>Original audit record</p><pre>{JSON.stringify(a, null, 2)}</pre></div></td></tr>}
            </Fragment>;
          })}</tbody>
        </table></div> : null}
    </Panel>
  </div>;
}
