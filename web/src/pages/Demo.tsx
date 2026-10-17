import {useState} from 'react';
import {Pause, Play, RotateCcw} from 'lucide-react';
import {useWard} from '../lib/store';
import {useCommand, useResource} from '../lib/hooks';
import {can, dateTime, time} from '../lib/domain';
import {ActionList, Feedback, PageTitle, Panel, Stats, Tip} from '../components/ui';
import {Dialog, Tabs} from '../components/extra';

const SCENARIOS = [
  {id: 'full_ward_script', name: 'Full ward script', what: 'The whole story on 12 beds: a real emergency, a loose clip, a drifting line, then a replay attack and a fake flatline.'},
  {id: 'emergency', name: 'Real emergency only', what: 'One bed deteriorates for real: alert, ladder and Telegram.'},
  {id: 'loose_sensor', name: 'Loose sensor', what: 'A finger clip comes loose: the false alarm is silenced and the nurse asked to refit it.'},
  {id: 'drifting', name: 'Drift', what: 'An arterial line drifts away from the cuff: biomed ticket.'},
  {id: 'replay_attack', name: 'Replay attack', what: 'Old normal readings are replayed over a monitor: grey stripes, cut-off, evidence.'},
  {id: 'fake_flatline', name: 'Fake flatline', what: 'An injected flatline on a healthy patient: the body witness disagrees.'},
  {id: 'flood', name: 'Flood', what: 'A monitor floods the network: the network witness catches it.'},
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
  return (
    <div className="page">
      <PageTitle eyebrow="S12 · Demo operator" title="Demo control" description="Run the ward script for the video, or reset the ward. Only the demo operator sees this screen." />
      <Stats items={[
        {label: 'Hub link', value: h ? (h.mqtt_connected ? 'Live' : 'Down') : '—', hint: 'Whether the backend is connected to the ward message hub (MQTT).'},
        {label: 'Beds online', value: h?.beds_online ?? '—', hint: 'Beds sending data now. 0 means no scenario is running.'},
        {label: 'Last message', value: h?.last_message_ts ? time(h.last_message_ts, true) : '—', hint: 'Time the backend last received anything from the hub.'},
        {label: 'Rejected messages', value: h?.invalid_messages ?? '—', hint: 'Messages that failed validation since the backend started.'},
      ]} />
      <div className="split-2">
        <Panel title="Scenario" caption="Pick what the simulated ward will do.">
          <div className="scenario-list" role="radiogroup" aria-label="Scenario">
            {SCENARIOS.map(s => (
              <label key={s.id} className={`scenario ${scenario === s.id ? 'is-on' : ''}`}>
                <input type="radio" name="scenario" value={s.id} checked={scenario === s.id} onChange={() => setScenario(s.id)} />
                <span><strong>{s.name}</strong><span className="tiny">{s.what}</span></span>
              </label>
            ))}
          </div>
        </Panel>
        <div>
          <Panel title="Controls" caption="Run publishes the scenario to the simulator; nothing changes until it starts sending.">
            <div className="row-actions">
              <span className="field-label">Speed</span>
              <Tabs label="Playback speed" value={speed} onChange={setSpeed} options={[
                {value: '1', label: '1×', hint: 'Real time.'}, {value: '2', label: '2×', hint: 'Twice as fast.'}, {value: '5', label: '5×', hint: 'Five times as fast.'},
              ]} />
            </div>
            <div className="row-actions">
              <button disabled={!allowed || run.pending} title="Start the chosen scenario at the chosen speed."
                      onClick={() => void run.run('/api/demo/run', {scenario, speed: Number(speed)})}><Play size={14} aria-hidden="true" /> Run</button>
              <Tip text="The backend has no pause command yet; Reset stops the run."><button disabled><Pause size={14} aria-hidden="true" /> Pause</button></Tip>
              <button className="danger-outline" disabled={!allowed || reset.pending} title="Stop the run and clear its data (beds and users are kept). Asks first."
                      onClick={() => setConfirm(true)}><RotateCcw size={14} aria-hidden="true" /> Reset ward</button>
            </div>
            <Feedback message={run.feedback || reset.feedback} failed={run.failed || reset.failed} />
          </Panel>
          <Panel title="What happens" caption="The chosen scenario, in plain words. Timings come from the simulator script.">
            <p>{SCENARIOS.find(s => s.id === scenario)?.what}</p>
            <p className="tiny">A step-by-step timeline is not available: the backend does not expose the scenario script.</p>
          </Panel>
          <Panel title="Demo history" caption="Recent run and reset actions.">
            <ActionList actions={demoActions} />
            {h?.last_message_ts && <p className="tiny">Ward last active {dateTime(h.last_message_ts)}.</p>}
          </Panel>
        </div>
      </div>
      <Dialog open={confirm} title="Reset the ward?" onClose={() => setConfirm(false)} actions={<>
        <button className="ghost" onClick={() => setConfirm(false)}>Cancel</button>
        <button className="danger" onClick={() => { setConfirm(false); void reset.run('/api/demo/reset', {}); }}>Yes, reset</button></>}>
        <p>This stops the current run and clears its alerts, actions, incidents, reports and tickets. Beds, users and the list of past runs are kept. It cannot be undone.</p>
      </Dialog>
    </div>
  );
}
