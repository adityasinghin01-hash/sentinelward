import {useMemo, useState} from 'react';
import {Link} from 'react-router-dom';
import {Ban, FileWarning, Radar, ShieldAlert, ShieldCheck, WifiOff} from 'lucide-react';
import {useWard} from '../lib/store';
import {useCommand, useNow, useResource} from '../lib/hooks';
import {age, can, countdown, score01, time} from '../lib/domain';
import type {AgentRecord, BedDetail, Device, NetFeatures} from '../lib/types';
import {ActionList, Empty, Feedback, PageTitle, Panel, ResourceState, Stats, Tip} from '../components/ui';
import {Chip, Dialog, Fact} from '../components/extra';
import {TrendChart} from '../components/Chart';

// Actions IT cares about: cut-offs, evidence, reports, fleet hunts (agents A2–A5) and staff security actions.
const SECURITY_ACTORS = new Set(['A2', 'A3', 'A4', 'A5']);
const SECURITY_CODES = /isolat|disable|reconnect|undo|evidence|snapshot|hash|incident|report|fleet|contain|resolve|clock/i;
const openIncident = (r: AgentRecord) => !['resolved', 'closed'].includes(String(r.data.status));

function DeviceStatus({d}: {d: Device}) {
  if (d.isolated) return <Chip kind="striped" hint={`Cut off from the ward network${d.isolated_since ? ` since ${time(d.isolated_since, true)}` : ''}. Undo reconnects it.`}><Ban size={12} aria-hidden="true" />Cut off</Chip>;
  if (!d.online) return <Chip kind="neutral" hint="The hub has not heard this monitor recently."><WifiOff size={12} aria-hidden="true" />Not heard</Chip>;
  return <Chip kind="info" hint="Online: the hub hears this monitor now."><ShieldCheck size={12} aria-hidden="true" />Online</Chip>;
}

function NetworkWitness({device}: {device: Device}) {
  const role = useWard(s => s.session?.role);
  const net = useResource<NetFeatures[]>(`/api/devices/${encodeURIComponent(device.device_id)}/network?minutes=10`, 10000);
  const bed = useResource<BedDetail>(`/api/beds/${encodeURIComponent(device.bed_id)}`, 6000);
  const cmd = useCommand();
  const [confirm, setConfirm] = useState(false);
  const rows = net.data ?? [];
  const series = useMemo(() => [{label: 'msg/s', color: '#80AEE5', values: rows.map(r => r.msgs_per_s)}], [rows]);
  const ts = useMemo(() => rows.map(r => r.window_start), [rows]);
  const last = rows[rows.length - 1] ?? device.net;
  const allowed = can(role, 'security');
  return (
    <Panel title={`Network witness · ${device.device_id}`} caption={`Bed ${device.bed_id} · last 10 minutes, one point per 5-second window.`}
           aside={<DeviceStatus d={device} />}>
      <TrendChart ts={ts} series={series} height={110} label={`Message rate of ${device.device_id} over the last 10 minutes`} />
      <dl className="facts facts-grid">
        <Fact label="Message rate" hint="Messages per second in the newest window. A healthy monitor sends about 1/s." value={last?.msgs_per_s == null ? '—' : `${last.msgs_per_s.toFixed(1)}/s`} />
        <Fact label="Senders" hint="How many different network senders used this monitor's identity. More than 1 suggests an impostor." value={last?.senders ?? '—'} />
        <Fact label="Timing jitter" hint="Spread of the time between messages, in ms. Replayed or injected traffic is often too regular or bursty." value={last?.iat_std_ms == null ? '—' : `${Math.round(last.iat_std_ms)} ms`} />
        <Fact label="Seq gaps / repeats" hint="Missing / repeated message numbers in the window. Repeats point to replay." value={`${last?.seq_gaps ?? '—'} / ${last?.seq_repeats ?? '—'}`} />
        <Fact label="Malformed" hint="Messages that failed format checks in the window." value={last?.malformed ?? '—'} />
        <Fact label="Freshness" hint="How old the newest reading from this monitor is." value={last?.stale_ms == null ? '—' : `${Math.round(last.stale_ms / 1000)} s old`} />
        <Fact label="Replay check (M4)" hint="Suspicion that old signal is being replayed, 0 to 1." value={score01(bed.data?.scores?.M4?.score)} />
        <Fact label="Network check (M5)" hint="Suspicion that the network traffic is an attack, 0 to 1." value={score01(bed.data?.scores?.M5?.score)} />
      </dl>
      {net.error && <p className="tiny">Network history unavailable: {net.error}</p>}
      <div className="row-actions">
        <button disabled={!allowed || device.isolated || cmd.pending} onClick={() => setConfirm(true)}
                title={!allowed ? 'Only IT security can cut off a device.' : device.isolated ? 'Already cut off. Use Undo in the feed to reconnect.' : 'Ask the network agent (A2) to cut this monitor off the ward network. Logged and undoable.'}>
          <Ban size={14} aria-hidden="true" /> Cut off device
        </button>
      </div>
      <Feedback message={cmd.feedback} failed={cmd.failed} />
      <Dialog open={confirm} title={`Cut off ${device.device_id}?`} onClose={() => setConfirm(false)} actions={<>
        <button className="ghost" onClick={() => setConfirm(false)}>Cancel</button>
        <button onClick={() => { setConfirm(false); void cmd.run(`/api/devices/${encodeURIComponent(device.device_id)}/isolate`, {type: 'isolate_device', deviceId: device.device_id, bedId: device.bed_id}); }}>
          Yes, cut it off
        </button></>}>
        <p>The monitor for Bed {device.bed_id} stops reaching the ward. The bed screen keeps the last trusted values with grey stripes and asks the nurse for hand checks.</p>
        <p className="tiny">The cut-off is logged and can be undone from the action feed.</p>
      </Dialog>
    </Panel>
  );
}

export function SecurityPage() {
  const role = useWard(s => s.session?.role);
  const beds = useWard(s => s.beds);
  const actions = useWard(s => s.actions);
  const now = useNow();
  const devices = useResource<Device[]>('/api/devices', 5000);
  const incidents = useResource<AgentRecord[]>('/api/incidents', 8000);
  const reports = useResource<AgentRecord[]>('/api/reports', 10000);
  const hunt = useCommand();
  const [selected, setSelected] = useState<string | null>(null);
  const [huntOpen, setHuntOpen] = useState(false);
  const [huntModel, setHuntModel] = useState('all');
  const list = devices.data ?? [];
  const device = list.find(d => d.device_id === selected) ?? list[0];
  const open = (incidents.data ?? []).filter(openIncident);
  const dues = (reports.data ?? []).filter(r => !['sent', 'human_marked_sent'].includes(String(r.data.status)))
    .map(r => Number(r.data.deadline_ts)).filter(n => n > 0);
  const due = dues.length ? Math.min(...dues) : null;
  const feed = actions.filter(a => SECURITY_ACTORS.has(a.actor) || SECURITY_CODES.test(a.action_code)).slice(0, 14);
  return (
    <div className="page">
      <PageTitle eyebrow="S6 · IT security" title="Security"
                 description="Monitors on the ward network, the network witness, cut-offs and their undo. Clinical alarms are not shown here.">
        <button disabled={!can(role, 'security') || hunt.pending} onClick={() => setHuntOpen(true)}
                title="Ask the fleet agent (A4) to watch every monitor of the same model for the same attack.">
          <Radar size={14} aria-hidden="true" /> Fleet hunt
        </button>
      </PageTitle>
      <Feedback message={hunt.feedback} failed={hunt.failed} />
      <Stats items={[
        {label: 'Devices', value: list.length || '—', hint: 'Bedside monitors known to the ward hub.', sub: `${list.filter(d => d.online).length} online now`},
        {label: 'Cut off', value: list.filter(d => d.isolated).length, hint: 'Monitors IT has cut off from the ward network.'},
        {label: 'Open incidents', value: open.length, hint: 'Security incidents not yet resolved (from the evidence agent A3).'},
        {label: 'Report clock', value: due ? countdown(due, now) : '—', hint: 'CERT-In asks for a report within 6 hours of noticing an incident. Time left on the earliest unsent report.', sub: due ? 'left on earliest report' : 'no report due'},
      ]} />
      <ResourceState loading={devices.loading && !list.length} error={devices.error} retry={() => void devices.reload()} />
      <div className="security-layout">
        <div>
          <Panel title="Devices" caption="Select a monitor to see its network witness. Data trust comes from the ward verdict.">
            {list.length === 0 && !devices.loading ? <Empty title="No devices reported" detail="The hub has not reported any monitors yet." /> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr>
                    <th scope="col">Device</th><th scope="col">Bed</th><th scope="col">Status</th>
                    <th scope="col"><Tip text="Messages per second, newest 5-second window."><span>Msg rate</span></Tip></th>
                    <th scope="col"><Tip text="Age of the newest message the hub received from this monitor."><span>Last heard</span></Tip></th>
                    <th scope="col"><Tip text="Different senders seen using this monitor's identity. More than 1 is suspicious."><span>Senders</span></Tip></th>
                    <th scope="col"><Tip text="Missing / repeated message numbers in the newest window."><span>Gaps / repeats</span></Tip></th>
                    <th scope="col"><Tip text="Data trust of the bed this monitor feeds, 0 to 1."><span>Data trust</span></Tip></th>
                  </tr></thead>
                  <tbody>
                    {list.map(d => {
                      const bed = beds.find(b => b.bed_id === d.bed_id);
                      const low = bed ? bed.trust_score < 50 : false;
                      return (
                        <tr key={d.device_id} tabIndex={0} className={device?.device_id === d.device_id ? 'is-selected' : ''}
                            aria-selected={device?.device_id === d.device_id} onClick={() => setSelected(d.device_id)}
                            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(d.device_id); } }}>
                          <td className="mono">{d.device_id}</td>
                          <td>{d.bed_id}</td>
                          <td><DeviceStatus d={d} /></td>
                          <td className="mono">{d.net?.msgs_per_s == null ? '—' : `${d.net.msgs_per_s.toFixed(1)}/s`}</td>
                          <td className="mono">{d.last_seen_ts ? age(d.last_seen_ts, now) : '—'}</td>
                          <td className="mono">{d.net?.senders ?? '—'}</td>
                          <td className="mono">{d.net?.seq_gaps ?? '—'} / {d.net?.seq_repeats ?? '—'}</td>
                          <td className={`mono ${low ? 'striped-cell' : ''}`}>{bed ? (bed.trust_score / 100).toFixed(2) : '—'}{low && <span className="sr-only"> low trust</span>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
          {device && <NetworkWitness key={device.device_id} device={device} />}
        </div>
        <aside>
          <Panel title="Incidents" caption="Opened by the evidence agent (A3) when a device looks attacked.">
            {open.length === 0 ? <Empty title="No open incidents" detail="Calm: no device is under investigation." /> : (
              <ul className="incident-list">
                {open.map(r => (
                  <li key={r.record_id}>
                    <ShieldAlert size={15} aria-hidden="true" />
                    <div>
                      <Link to={`/incident/${encodeURIComponent(r.record_id)}`} className="inline-link" title="Open the incident timeline and evidence.">
                        {String(r.data.device_id ?? 'Device')} · Bed {String(r.data.bed_id ?? '—')}
                      </Link>
                      <p className="tiny">{String(r.data.status ?? 'open').replace(/_/g, ' ')} · since {time(r.ts, true)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <Link to="/incident" className="tiny inline-link" title="All incidents, including resolved ones.">All incidents</Link>
          </Panel>
          <Panel title="Live attack feed" caption="Security actions by agents and staff. Automatic ones show Undo.">
            <ActionList actions={feed} />
          </Panel>
          <p className="tiny"><FileWarning size={12} aria-hidden="true" /> Model and firmware columns are not available: the devices API does not report them yet.</p>
        </aside>
      </div>
      <Dialog open={huntOpen} title="Start a fleet hunt?" onClose={() => setHuntOpen(false)} actions={<>
        <button className="ghost" onClick={() => setHuntOpen(false)}>Cancel</button>
        <button onClick={() => { setHuntOpen(false); void hunt.run('/api/fleet-hunt', {type: 'fleet_hunt', model: huntModel.trim() || 'all'}); }}>Start hunt</button></>}>
        <p>The fleet agent (A4) watches every monitor of this model for the same attack pattern and reports what it finds in the feed.</p>
        <label className="field">Monitor model<input value={huntModel} onChange={e => setHuntModel(e.target.value)} maxLength={128} /></label>
        <p className="tiny">“all” watches every monitor on the ward.</p>
      </Dialog>
    </div>
  );
}
