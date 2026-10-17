import {useState} from 'react';
import {Check, ChevronsUp, ExternalLink} from 'lucide-react';
import {useNavigate} from 'react-router-dom';
import {useWard} from '../lib/store';
import {useCommand, useNow} from '../lib/hooks';
import {age, can, isAckedAlert, isAutoClosedAlert, isOpenAlert, time} from '../lib/domain';
import type {Alert} from '../lib/types';
import {BedLink, Button, Dialog, Empty, Feedback, Panel, ResourceState, SegmentedControl, StateChip} from '../components/ui';
import {alertLine} from '../components/ward/tile';
import {PageHeader} from '../components/pages/PageHeader';
import {actorName} from '../components/pages/actions';

type Filter = 'open' | 'acked' | 'closed' | 'all';
const PRIORITY = {high: 0, medium: 1, low: 2, none: 3} as const;
const LADDER = [
  {step: 1, who: 'Assigned nurse', hint: 'The nurse assigned to this bed is notified first.'},
  {step: 2, who: 'Next nurse', hint: 'A second nurse is added if nobody acknowledges.'},
  {step: 3, who: 'All nurses and doctor', hint: 'The whole ward team is notified.'},
];
const recipients = (a: Alert) => a.to.map(actorName).join(', ') || 'Ward team';

function LadderDots({step}: {step: number}) {
  return <span className="pages-ladder"><span className="ladder-dots" aria-hidden="true">{[1, 2, 3].map(i => <i key={i} className={i <= step ? 'on' : ''} />)}</span><span>Step {step} of 3</span></span>;
}

function AlertSheet({alert, onClose}: {alert: Alert; onClose: () => void}) {
  const role = useWard(s => s.session?.role);
  const cmd = useCommand();
  const now = useNow();
  const clinical = can(role, 'clinical');
  const open = isOpenAlert(alert);
  return <Dialog open title={`Alert · ${alert.bed_id}`} onClose={onClose} actions={null}><div className="pages-alert-sheet">
    <StateChip state={alert.verdict} />
    <p className="sheet-cause">{alertLine(alert)}</p>
    <p className="tiny muted">Raised <time className="mono">{time(alert.ts, true)}</time> · {open ? `waiting ${age(alert.ts, now)}` : isAckedAlert(alert) ? `acknowledged by ${actorName(alert.acked_by || 'Staff')}` : 'closed automatically'}</p>
    <h3 className="sub-heading">Who has been notified</h3>
    <p className="sheet-recipients">{recipients(alert)}</p>
    <ol className="ladder pages-escalation">{LADDER.map(l => <li key={l.step} className={alert.ladder_step >= l.step ? 'reached' : ''}>
      <span className="ladder-number" aria-hidden="true">{l.step}</span><div><strong>{l.who}</strong><p className="tiny">{l.hint}</p></div>
    </li>)}</ol>
    <div className="sheet-actions">
      <Button variant="primary" size={44} disabled={!clinical || !open} pending={cmd.pending}
        hint={clinical ? 'I am on it: stops the escalation ladder.' : 'Only nurses and doctors acknowledge alerts.'}
        onClick={() => void cmd.run(`/api/alerts/${encodeURIComponent(alert.alert_id)}/ack`, {})}><Check size={16} aria-hidden="true" />Acknowledge</Button>
      <Button disabled={!clinical || !open || alert.ladder_step >= 3} pending={cmd.pending}
        onClick={() => void cmd.run(`/api/alerts/${encodeURIComponent(alert.alert_id)}/escalate`, {type: 'escalate_alert', alertId: alert.alert_id, bedId: alert.bed_id})}><ChevronsUp size={16} aria-hidden="true" />Escalate</Button>
    </div>
    {open && alert.ladder_step >= 3 && <p className="tiny muted">Already at the final step. All nurses and the doctor have been notified.</p>}
    {!clinical && open && <p className="tiny muted">A nurse or doctor must acknowledge this alert.</p>}
    <Feedback message={cmd.feedback} failed={cmd.failed} />
    <details className="record-details sheet-record"><summary>Original alert</summary><div className="record-original"><pre>{JSON.stringify(alert, null, 2)}</pre></div></details>
  </div></Dialog>;
}

function AlertActions({alert}: {alert: Alert}) {
  const role = useWard(s => s.session?.role);
  const cmd = useCommand();
  const navigate = useNavigate();
  return <div className="pages-alert-actions" onClick={e => e.stopPropagation()}>
    {isOpenAlert(alert) && <Button variant="primary" size={44} aria-label={`Acknowledge ${alert.bed_id}`} disabled={!can(role, 'clinical')} pending={cmd.pending}
      hint={can(role, 'clinical') ? 'I am on it: stops the escalation ladder.' : 'Only nurses and doctors acknowledge alerts.'}
      onClick={() => void cmd.run(`/api/alerts/${encodeURIComponent(alert.alert_id)}/ack`, {})}><Check size={15} aria-hidden="true" />Acknowledge</Button>}
    <Button size={40} variant="secondary" onClick={() => navigate(`/bed/${alert.bed_id}`)} aria-label={`Open bed ${alert.bed_id}`}><ExternalLink size={14} aria-hidden="true" />Open</Button>
    <Feedback message={cmd.feedback} failed={cmd.failed} />
  </div>;
}

export function AlertsPage() {
  const alerts = useWard(s => s.alerts);
  const receivedAt = useWard(s => s.receivedAt);
  const error = useWard(s => s.error);
  const loading = !receivedAt && !alerts.length && !error;
  const now = useNow();
  const [filter, setFilter] = useState<Filter>('open');
  const [selected, setSelected] = useState<string | null>(null);
  const shown = alerts.filter(a => filter === 'all' || (filter === 'open' ? isOpenAlert(a) : filter === 'acked' ? isAckedAlert(a) : isAutoClosedAlert(a)))
    .sort((a, b) => Number(isOpenAlert(b)) - Number(isOpenAlert(a)) || PRIORITY[a.priority] - PRIORITY[b.priority] || b.ts - a.ts);
  const current = alerts.find(a => a.alert_id === selected) ?? null;
  const counts = {open: alerts.filter(isOpenAlert).length, acked: alerts.filter(isAckedAlert).length, closed: alerts.filter(isAutoClosedAlert).length, all: alerts.length};
  return <div className="page pages-page alerts-page">
    <PageHeader title="Alerts" description="The bed, the reason, and the people responding. Select a row to see the escalation.">
      <SegmentedControl label="Filter alerts" value={filter} onChange={setFilter} options={[
        {value: 'open', label: `Open · ${counts.open}`}, {value: 'acked', label: `Acknowledged · ${counts.acked}`},
        {value: 'closed', label: `Auto-closed · ${counts.closed}`}, {value: 'all', label: `All · ${counts.all}`},
      ]} />
    </PageHeader>
    <ResourceState loading={loading} error={error || ''} />
    <div className="split">
      <Panel title={!receivedAt && !alerts.length ? 'Alerts' : `${shown.length} ${filter === 'all' ? '' : filter === 'open' ? 'open ' : filter === 'acked' ? 'acknowledged ' : 'auto-closed '}alert${shown.length === 1 ? '' : 's'}`}
        caption="Acknowledge when you are responding. Repeated signals update the same alert.">
        {!shown.length && !loading ? <Empty title={filter === 'open' ? 'No open alerts' : 'No alerts in this view'} detail="New alerts appear here when a bed needs attention." /> : shown.length > 0 ?
          <div className="table-wrap"><table className="table alerts-table">
            <thead><tr><th scope="col">State</th><th scope="col">Bed</th><th scope="col">What needs attention</th><th scope="col">Waiting</th><th scope="col">Escalation</th><th scope="col">Sent to</th><th scope="col">Respond</th></tr></thead>
            <tbody>{shown.map(a => <tr key={a.alert_id} className={selected === a.alert_id ? 'is-selected' : ''} onClick={() => setSelected(a.alert_id)} tabIndex={0}
              onKeyDown={e => {if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {e.preventDefault(); setSelected(a.alert_id);}}} aria-selected={selected === a.alert_id}>
              <td><StateChip state={a.verdict} /></td><td><BedLink id={a.bed_id} /></td><td className="alert-reason">{alertLine(a)}</td>
              <td className="alert-wait">{isOpenAlert(a) ? <span className="mono">{age(a.ts, now)}</span> : isAckedAlert(a) ? `Taken by ${actorName(a.acked_by || 'Staff')}` : 'Auto-closed'}</td>
              <td><LadderDots step={a.ladder_step} /></td><td className="alert-to">{recipients(a)}</td><td><AlertActions alert={a} /></td>
            </tr>)}</tbody>
          </table></div> : null}
      </Panel>
      {current && <AlertSheet alert={current} onClose={() => setSelected(null)} />}
    </div>
  </div>;
}
