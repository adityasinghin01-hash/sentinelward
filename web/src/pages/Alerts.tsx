import {useState} from 'react';
import {Check, ChevronsUp, ExternalLink, X} from 'lucide-react';
import {useNavigate} from 'react-router-dom';
import {useWard} from '../lib/store';
import {useCommand, useNow} from '../lib/hooks';
import {age, can, staff, time, verdictWords} from '../lib/domain';
import type {Alert} from '../lib/types';
import {Badge, BedLink, Empty, Feedback, PageTitle, Panel, Tip} from '../components/ui';
import {Tabs} from '../components/extra';

type Filter = 'open' | 'acked' | 'all';
const PRIORITY = {high: 0, medium: 1, low: 2, none: 3} as const;
const LADDER = [
  {step: 1, who: 'Assigned nurse', hint: 'The nurse assigned to this bed gets the alert first.'},
  {step: 2, who: 'Next nurse', hint: 'If nobody acknowledges within 30 s (demo; 60 s in the real design), the next nurse is added.'},
  {step: 3, who: 'All nurses + doctor', hint: 'After another 30 s without an acknowledgement, everyone on the ward and the doctor are alerted.'},
];
const isOpen = (a: Alert) => a.status === 'open' || a.status === 'escalated';

function AlertSheet({alert, onClose}: {alert: Alert; onClose: () => void}) {
  const role = useWard(s => s.session?.role);
  const cmd = useCommand();
  const now = useNow();
  const clinical = can(role, 'clinical');
  return (
    <aside className="sheet" aria-label={`Alert details for ${alert.bed_id}`}>
      <div className="sheet-head">
        <Badge tone={alert.priority}>{alert.priority.toUpperCase()}</Badge>
        <h2>{alert.bed_id} · {verdictWords[alert.verdict] ?? alert.verdict}</h2>
        <button className="icon-button" onClick={onClose} title="Close the details panel"><X size={16} aria-hidden="true" /><span className="sr-only">Close</span></button>
      </div>
      <p className="tiny">Raised {time(alert.ts, true)} · {isOpen(alert) ? `waiting ${age(alert.ts, now)}` : `acknowledged by ${staff(alert.acked_by)} at ${time(alert.acked_ts, true)}`}</p>
      <h3 className="sub-heading">Escalation ladder</h3>
      <ol className="ladder">
        {LADDER.map(l => {
          const reached = alert.ladder_step >= l.step;
          return (
            <li key={l.step} className={reached ? 'reached' : ''}>
              <Tip text={l.hint}><span className="ladder-dot" aria-hidden="true">{reached ? '●' : '○'}</span></Tip>
              <div>
                <strong>Step {l.step} · {l.who}</strong>
                <p className="tiny">{reached ? (l.step === alert.ladder_step ? `current step · sent to ${alert.to.map(staff).join(', ') || 'ward'}` : 'reached') : 'not reached'}</p>
              </div>
            </li>
          );
        })}
      </ol>
      <p className="tiny">Per-step send times are not in the alert record; the backend reports the current step and recipients only.</p>
      <h3 className="sub-heading">Message as sent</h3>
      <blockquote className="message">{alert.text}</blockquote>
      <div className="sheet-actions">
        <button disabled={!clinical || !isOpen(alert) || cmd.pending} title={clinical ? 'I am on it: stops the escalation ladder.' : 'Only nurses and doctors acknowledge alerts.'}
                onClick={() => void cmd.run(`/api/alerts/${encodeURIComponent(alert.alert_id)}/ack`, {})}>
          <Check size={14} aria-hidden="true" /> Acknowledge
        </button>
        <button disabled={!clinical || !isOpen(alert) || alert.ladder_step >= 3 || cmd.pending}
                title={clinical ? 'Move this alert to the next ladder step now.' : 'Only nurses and doctors escalate alerts.'}
                onClick={() => void cmd.run(`/api/alerts/${encodeURIComponent(alert.alert_id)}/escalate`, {type: 'escalate_alert', alertId: alert.alert_id, bedId: alert.bed_id})}>
          <ChevronsUp size={14} aria-hidden="true" /> Escalate
        </button>
      </div>
      <Feedback message={cmd.feedback} failed={cmd.failed} />
    </aside>
  );
}

export function AlertsPage() {
  const alerts = useWard(s => s.alerts);
  const now = useNow();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>('open');
  const [selected, setSelected] = useState<string | null>(null);
  const shown = alerts
    .filter(a => filter === 'all' || (filter === 'open' ? isOpen(a) : !isOpen(a)))
    .sort((a, b) => (isOpen(b) ? 1 : 0) - (isOpen(a) ? 1 : 0) || PRIORITY[a.priority] - PRIORITY[b.priority] || b.ts - a.ts);
  const current = alerts.find(a => a.alert_id === selected) ?? null;
  const counts = {open: alerts.filter(isOpen).length, acked: alerts.filter(a => !isOpen(a)).length, all: alerts.length};
  return (
    <div className="page">
      <PageTitle eyebrow="S4 · Alerts and escalation" title="Alerts"
                 description="Every alert, who has it, how long it has waited, and where it is on the escalation ladder.">
        <Tabs label="Filter alerts" value={filter} onChange={setFilter} options={[
          {value: 'open', label: 'Open', hint: 'Alerts nobody has acknowledged yet.', count: counts.open},
          {value: 'acked', label: 'Acknowledged', hint: 'Alerts someone has taken.', count: counts.acked},
          {value: 'all', label: 'All', hint: 'Every alert in this run.', count: counts.all},
        ]} />
      </PageTitle>
      <div className={`split ${current ? 'with-sheet' : ''}`}>
        <Panel title={`${shown.length} ${filter === 'all' ? '' : filter === 'open' ? 'open ' : 'acknowledged '}alert${shown.length === 1 ? '' : 's'}`}
               caption="One alert per bed per event: repeats update the same row. Select a row for the ladder.">
          {shown.length === 0 ? (
            <Empty title={filter === 'open' ? 'No open alerts. All beds calm.' : 'No alerts here'} detail="New alerts appear here within a second of the AI raising them." />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr>
                  <th scope="col">Time</th><th scope="col">Bed</th><th scope="col">Priority</th><th scope="col">What</th>
                  <th scope="col"><Tip text="Staff who received the alert at the current ladder step."><span>Sent to</span></Tip></th>
                  <th scope="col"><Tip text="1 = assigned nurse, 2 = next nurse, 3 = all nurses + doctor."><span>Ladder</span></Tip></th>
                  <th scope="col"><Tip text="Time since the alert was raised (open) or who acknowledged it."><span>Waiting</span></Tip></th>
                  <th scope="col"><span className="sr-only">Open</span></th>
                </tr></thead>
                <tbody>
                  {shown.map(a => (
                    <tr key={a.alert_id} className={`row-${a.priority} ${selected === a.alert_id ? 'is-selected' : ''}`}
                        onClick={() => setSelected(a.alert_id)} tabIndex={0}
                        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(a.alert_id); } }}
                        aria-selected={selected === a.alert_id}>
                      <td className="mono">{time(a.ts, true)}</td>
                      <td><BedLink id={a.bed_id} /></td>
                      <td><Badge tone={a.priority}>{a.priority === 'none' ? 'INFO' : a.priority.toUpperCase()}</Badge></td>
                      <td className="what">{a.text}</td>
                      <td>{a.to.map(staff).join(', ') || 'Ward'}</td>
                      <td className="mono">{a.ladder_step} / 3</td>
                      <td className="mono">{isOpen(a) ? age(a.ts, now) : `✓ ${staff(a.acked_by)}`}</td>
                      <td><button className="button-small ghost" title="Open this bed's readings and evidence."
                                  onClick={e => { e.stopPropagation(); navigate(`/bed/${a.bed_id}`); }}>
                        <ExternalLink size={13} aria-hidden="true" /><span className="sr-only">Open bed {a.bed_id}</span></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        {current && <AlertSheet alert={current} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}
