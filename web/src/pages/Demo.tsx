import {useState} from 'react';
import {Pause, Play, RotateCcw} from 'lucide-react';
import {useWard} from '../lib/store';
import {useCommand, useResource} from '../lib/hooks';
import {can, dateTime, time} from '../lib/domain';
import {Button, Chip, ConfirmDialog, Feedback, Panel, ResourceState, Stats} from '../components/ui';
import {Tabs} from '../components/extra';
import {PageHeader} from '../components/pages/PageHeader';
import {ActionFeed} from '../components/pages/ActionRecord';

const SCENARIOS = [
  {id: 'full_ward_script', name: 'Full ward script', what: 'Twelve beds: a real emergency, a loose sensor, pressure drift, a replay attack, and a fake flatline.'},
  {id: 'emergency', name: 'Real emergency only', what: 'One patient deteriorates: an alert is sent and escalated until someone responds.'},
  {id: 'loose_sensor', name: 'Loose sensor', what: 'A finger sensor comes loose: the nurse is asked to refit it. Monitor alarms remain active.'},
  {id: 'drifting', name: 'Sensor drift', what: 'An arterial pressure line drifts away from the cuff reading and a repair ticket is opened.'},
  {id: 'replay_attack', name: 'Replay attack', what: 'Old readings are replayed over a monitor. The monitor is cut off and evidence is preserved.'},
  {id: 'fake_flatline', name: 'Fake flatline', what: 'A false flatline is injected while the patient’s other signals still show a pulse.'},
  {id: 'flood', name: 'Network flood', what: 'A monitor floods the network and the network checks detect the unusual traffic.'},
] as const;
type Speed = '1' | '2' | '5';
interface Health {ok: boolean; mqtt_connected: boolean; db_ok: boolean; beds_online: number; last_message_ts: number | null; invalid_messages: number}

export function DemoPage() {
  const role = useWard(s => s.session?.role);
  const actions = useWard(s => s.actions);
  const health = useResource<Health>('/api/health', 5000);
  const run = useCommand();
  const reset = useCommand();
  const [scenario, setScenario] = useState<string>('full_ward_script');
  const [speed, setSpeed] = useState<Speed>('1');
  const [confirm, setConfirm] = useState(false);
  const allowed = can(role, 'demo');
  const h = health.data;
  const demoActions = actions.filter(a => /demo|reset|run/i.test(a.action_code)).slice(0, 8);
  const chosen = SCENARIOS.find(s => s.id === scenario)!;
  return <div className="page pages-page demo-page">
    <PageHeader title="Demo control" description="Choose a scenario and playback speed. These controls affect the shared demo ward."><Chip>Synthetic data · Demo operator</Chip></PageHeader>
    <ResourceState loading={health.loading && !h} error={health.error} retry={() => void health.reload()} />
    <Stats items={[
      {label: 'Hub connection', value: h ? h.mqtt_connected ? 'Live' : 'Disconnected' : '—', hint: 'Whether the ward hub is connected.'},
      {label: 'Beds online', value: h?.beds_online ?? '—', hint: 'Beds currently sending data.'},
      {label: 'Last message', value: h?.last_message_ts ? time(h.last_message_ts, true) : '—', hint: 'When the ward hub last received a message.'},
      {label: 'Rejected messages', value: h?.invalid_messages ?? '—', hint: 'Messages that did not pass validation since the hub started.'},
    ]} />
    <div className="demo-layout">
      <Panel title="Choose a scenario" caption="Each scenario uses simulated bedside signals.">
        <div className="scenario-list" role="radiogroup" aria-label="Scenario">{SCENARIOS.map((s, i) => <label key={s.id} className={`scenario ${scenario === s.id ? 'is-on' : ''}`}>
          <input type="radio" name="scenario" value={s.id} checked={scenario === s.id} onChange={() => setScenario(s.id)} />
          <span><strong>{s.name}</strong><span className="tiny">{s.what}</span></span><span className="scenario-number mono" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
        </label>)}</div>
      </Panel>
      <div className="demo-controls">
        <Panel title="Playback" caption="The selected scenario starts only when you choose Run.">
          <h3 className="demo-chosen">{chosen.name}</h3><p className="demo-chosen-description">{chosen.what}</p>
          <div className="demo-speed"><span>Playback speed</span><Tabs label="Playback speed" value={speed} onChange={setSpeed} options={[
            {value: '1', label: '1×', hint: 'Real time.'}, {value: '2', label: '2×', hint: 'Twice as fast.'}, {value: '5', label: '5×', hint: 'Five times as fast.'},
          ]} /></div>
          <div className="row-actions"><Button variant="primary" disabled={!allowed} pending={run.pending} onClick={() => void run.run('/api/demo/run', {scenario, speed: Number(speed)})}><Play size={16} aria-hidden="true" />Run</Button>
            <Button disabled hint="Pause is unavailable in this simulator."><Pause size={16} aria-hidden="true" />Pause</Button></div>
          <p className="tiny muted">Pause is unavailable. Reset stops the run and clears its data.</p><Feedback message={run.feedback} failed={run.failed} />
        </Panel>
        <Panel title="Reset the shared ward" caption="Stop the current run and clear its alerts, actions, incidents, reports and tickets.">
          <p className="tiny muted">Beds, users and past runs are kept. Cleared data cannot be restored.</p>
          <Button variant="danger" disabled={!allowed || reset.pending} onClick={() => setConfirm(true)}><RotateCcw size={16} aria-hidden="true" />Reset ward</Button><Feedback message={reset.feedback} failed={reset.failed} />
        </Panel>
        <Panel title="Demo history" caption="Recent run and reset commands.">
          {demoActions.length ? <ActionFeed actions={demoActions} /> : <div className="demo-history-empty"><Play size={20} aria-hidden="true" /><p>No demo commands recorded</p><span>Run and reset commands will appear here.</span></div>}
          {h?.last_message_ts && <p className="tiny muted">Ward last active <span className="mono">{dateTime(h.last_message_ts)}</span>.</p>}
        </Panel>
      </div>
    </div>
    <ConfirmDialog open={confirm} title="Reset the ward?" bed="Shared demo ward" monitor="All monitor records" actionLabel="Yes, reset" pending={reset.pending}
      consequence="This stops the run and clears its alerts, actions, incidents, reports and tickets. Beds, users and the list of past runs are kept. Cleared data cannot be restored."
      onClose={() => setConfirm(false)} onConfirm={() => {setConfirm(false); void reset.run('/api/demo/reset', {});}} />
  </div>;
}
