import {useMemo, useState} from 'react';
import {Link} from 'react-router-dom';
import {Activity, AlertTriangle, Ban, Circle, Radar, ShieldAlert, ShieldCheck, WifiOff} from 'lucide-react';
import {useWard} from '../lib/store';
import {useCommand, useNow, useResource} from '../lib/hooks';
import {age, can, certDeadline, countdown, score01, time} from '../lib/domain';
import type {Action, AgentRecord, BedDetail, Device, NetFeatures} from '../lib/types';
import {Button, Chip, ConfirmDialog, Dialog, Empty, Feedback, Panel, ResourceState, Stats, Tooltip} from '../components/ui';
import {Fact} from '../components/extra';
import {TrendChart} from '../components/Chart';
import {tileView} from '../components/ward/tile';
import type {TileView} from '../components/ward/tile';
import {PageHeader} from '../components/pages/PageHeader';
import {ActionFeed, UndoAction} from '../components/pages/ActionRecord';
import {plainText} from '../components/pages/actions';

const SECURITY_ACTORS = new Set(['A2', 'A3', 'A4', 'A5']);
const SECURITY_CODES = /isolat|disable|reconnect|undo|evidence|snapshot|hash|incident|report|fleet|contain|resolve|clock/i;
const openIncident = (r: AgentRecord) => !['resolved', 'closed'].includes(String(r.data.status));
const SENDERS_HINT = 'Distinct senders using this monitor’s identity in the newest known 5-second window. More than one may mean an impostor.';
function senders(d: Device) {
  const n = d.senders ?? d.net?.senders;
  return typeof n === 'number' ? `${n} ${n === 1 ? 'sender' : 'senders'}` : 'Count unavailable';
}
function DeviceStatus({d}: {d: Device}) {
  return <Chip className={`device-status ${d.isolated ? 'status-cutoff' : d.online ? 'status-online' : 'status-quiet'}`}>
    {d.isolated ? <Ban size={13} aria-hidden="true" /> : d.online ? <Circle size={9} aria-hidden="true" /> : <WifiOff size={13} aria-hidden="true" />}
    {d.isolated ? 'Data untrusted · device flagged' : d.online ? 'Online' : 'Not heard'}
  </Chip>;
}
function DeviceState({view, device}: {view: TileView | null; device: Device}) {
  if (!view && device.isolated) return <span className="state-chip state-security"><Ban size={14} aria-hidden="true" />Data untrusted · device flagged</span>;
  const Icon = view?.group === 'security' ? ShieldAlert : view?.group === 'normal' ? Circle : view?.group === 'maint' ? Activity : AlertTriangle;
  return <span className={`state-chip state-${view?.tone || 'nodata'}`}><Icon size={14} aria-hidden="true" />{view?.word || (device.online ? 'Awaiting first signal' : 'No signal')}</span>;
}
function DeviceAction({d, actions}: {d: Device; actions: Action[]}) {
  const role = useWard(s => s.session?.role);
  const cmd = useCommand();
  const [confirm, setConfirm] = useState(false);
  const original = actions.find(a => a.device_id === d.device_id && a.mode === 'automatic' && a.undoable && /disable_client|isolate_device/.test(a.action_code));
  if (d.isolated) return original ? <UndoAction action={original} /> : <Button size={36} disabled hint="The reversible isolation record is not in the recent action history.">Undo</Button>;
  return <span className="pages-undo">
    <Button size={36} aria-label={`Isolate ${d.device_id}`} disabled={!can(role, 'security')} pending={cmd.pending} onClick={() => setConfirm(true)}><Ban size={14} aria-hidden="true" />Isolate</Button>
    <ConfirmDialog open={confirm} title="Isolate monitor?" bed={d.bed_id} monitor={d.device_id}
      consequence="Signals from this monitor stop reaching the ward. Last trusted values remain visible. Check the patient by hand until IT verifies the monitor. This action is logged and can be undone."
      actionLabel="Isolate monitor" pending={cmd.pending} onClose={() => setConfirm(false)} onConfirm={() => {setConfirm(false); void cmd.run(`/api/devices/${encodeURIComponent(d.device_id)}/isolate`, {type: 'isolate_device', deviceId: d.device_id, bedId: d.bed_id});}} />
    <Feedback message={cmd.feedback} failed={cmd.failed} />
  </span>;
}

function NetworkWitness({device}: {device: Device}) {
  const net = useResource<NetFeatures[]>(`/api/devices/${encodeURIComponent(device.device_id)}/network?minutes=10`, 10000);
  const bed = useResource<BedDetail>(`/api/beds/${encodeURIComponent(device.bed_id)}`, 6000);
  const rows = net.data ?? [];
  const series = useMemo(() => [{label: 'msg/s', color: 'var(--wave-ecg)', values: rows.map(r => r.msgs_per_s)}], [rows]);
  const ts = useMemo(() => rows.map(r => r.window_start), [rows]);
  const last = rows[rows.length - 1] ?? device.net;
  return <Panel title={`Network activity · ${device.device_id}`} caption={`${device.bed_id} · last 10 minutes · messages per second`} aside={<DeviceStatus d={device} />}>
    <ResourceState loading={net.loading && !net.data} error={net.error} retry={() => void net.reload()} />
    {rows.length ? <TrendChart ts={ts} series={series} height={150} label={`Messages per second for ${device.device_id}, last 10 minutes`} /> : !net.loading && <p className="network-empty">No network history received for this monitor.</p>}
    <dl className="facts facts-grid network-facts">
      <Fact label="Message rate" hint="Messages per second in the newest window. A healthy monitor sends about one per second." value={last?.msgs_per_s == null ? 'Not recorded' : `${last.msgs_per_s.toFixed(1)}/s`} />
      <Fact label="Senders" hint={SENDERS_HINT} value={senders(device)} />
      <Fact label="Newest reading" hint="Age of the newest signal in this network window." value={last?.stale_ms == null ? 'Not recorded' : `${Math.round(last.stale_ms / 1000)} s old`} />
      <Fact label="Missing / repeated" hint="Missing or repeated message numbers. Repeated numbers may indicate replay." value={last?.seq_gaps == null && last?.seq_repeats == null ? 'Not recorded' : `${last?.seq_gaps ?? '—'} / ${last?.seq_repeats ?? '—'}`} />
    </dl>
    <details className="record-details network-details"><summary>Engineering details</summary><dl className="facts facts-grid network-facts">
      <Fact label="Timing variation" hint="Variation between message arrival times, in milliseconds." value={last?.iat_std_ms == null ? 'Not recorded' : `${Math.round(last.iat_std_ms)} ms`} />
      <Fact label="Invalid messages" hint="Messages that did not pass format checks." value={last?.malformed ?? 'Not recorded'} />
      <Fact label="Replay check (M4)" hint="Suspicion of old signals being replayed, from zero to one." value={score01(bed.data?.scores?.M4?.score)} />
      <Fact label="Network check (M5)" hint="Suspicion of a network attack, from zero to one." value={score01(bed.data?.scores?.M5?.score)} />
    </dl></details>
  </Panel>;
}

export function SecurityPage() {
  const role = useWard(s => s.session?.role);
  const beds = useWard(s => s.beds);
  const alerts = useWard(s => s.alerts);
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
    .map(r => certDeadline(r, (incidents.data ?? []).find(i => i.record_id === r.data.incident_id))).filter((n): n is number => !!n);
  const due = dues.length ? Math.min(...dues) : null;
  const feed = actions.filter(a => SECURITY_ACTORS.has(a.actor) || SECURITY_CODES.test(a.action_code)).slice(0, 8);
  return <div className="page pages-page security-page">
    <PageHeader title="Security" description="Watch for device attacks, manage monitor cut-offs, and review the evidence.">
      <Button disabled={!can(role, 'security')} pending={hunt.pending} onClick={() => setHuntOpen(true)}><Radar size={16} aria-hidden="true" />Fleet hunt</Button>
    </PageHeader>
    <Feedback message={hunt.feedback} failed={hunt.failed} />
    <Stats items={[
      {label: 'Monitors', value: devices.data ? list.length : '—', hint: 'Monitors known to the ward hub.', sub: devices.data ? `${list.filter(d => d.online).length} online now` : 'awaiting the monitor list'},
      {label: 'Flagged', value: devices.data ? list.filter(d => d.isolated).length : '—', hint: 'Devices flagged as untrusted; completed cut-offs are recorded in the action history.'},
      {label: 'Open incidents', value: incidents.data ? open.length : '—', hint: 'Incidents still being investigated.'},
      {label: 'Report clock', value: due ? countdown(due, now) : '—', hint: 'Time left on the earliest unsent report.', sub: !reports.data ? 'checking report deadlines' : due ? 'left on earliest report' : 'no report due'},
    ]} />
    <ResourceState loading={devices.loading && !devices.data} error={devices.error} retry={() => void devices.reload()} />
    <Panel title="Ward monitors" caption="Select a row for network activity. Isolate and Undo always ask for confirmation.">
      {!list.length && !devices.loading ? <Empty title="No monitors reported" detail="Monitors appear when the ward hub reports them." /> : <div className="table-wrap"><table className="table devices-table">
        <thead><tr><th scope="col">Monitor</th><th scope="col">Bed</th><th scope="col">Connection</th><th scope="col">State</th><th scope="col">Last heard</th><th scope="col">Senders</th><th scope="col">Control</th></tr></thead>
        <tbody>{list.map(d => {
          const bed = beds.find(b => b.bed_id === d.bed_id);
          const view = bed ? tileView(bed, alerts, now) : null;
          return <tr key={d.device_id} tabIndex={0} className={device?.device_id === d.device_id ? 'is-selected' : ''} aria-selected={device?.device_id === d.device_id} onClick={() => setSelected(d.device_id)}
            onKeyDown={e => {if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {e.preventDefault(); setSelected(d.device_id);}}}>
            <td className="mono device-name">{d.device_id}</td><td className="mono">{d.bed_id}</td><td><DeviceStatus d={d} /></td><td><DeviceState view={view} device={d} /></td>
            <td className="mono muted">{d.last_seen_ts ? `${age(d.last_seen_ts, now)} ago` : 'Never received'}</td>
            <td><Tooltip text={SENDERS_HINT}><span className={`sender-count ${(d.senders ?? d.net?.senders ?? 0) > 1 ? 'multiple-senders' : ''}`}>{senders(d)}</span></Tooltip></td>
            <td onClick={e => e.stopPropagation()}><DeviceAction d={d} actions={actions} /></td>
          </tr>;
        })}</tbody>
      </table></div>}
    </Panel>
    <div className="security-detail-layout">
      <div>{device && <NetworkWitness key={device.device_id} device={device} />}
        <Panel title="Recent security actions" caption="Who acted and why. Original records are kept in Details." aside={<Link to="/log" className="inline-link">Action log</Link>}><ActionFeed actions={feed} /></Panel>
      </div>
      <Panel title="Open incidents" caption="Evidence frozen for monitors that may be under attack.">
        <ResourceState loading={incidents.loading && !incidents.data} error={incidents.error} retry={() => void incidents.reload()} />
        {incidents.data && !open.length ? <Empty title="No open incidents" detail="No monitor is currently under investigation." /> : <ul className="incident-list security-incidents">{open.map(r => <li key={r.record_id}>
          <ShieldAlert size={18} aria-hidden="true" /><div><Link to={`/incident/${encodeURIComponent(r.record_id)}`} className="inline-link">{String(r.data.device_id ?? 'Monitor')} · {String(r.data.bed_id ?? 'Bed not recorded')}</Link>
            <p className="tiny">{plainText(String(r.data.status ?? 'open').replace(/_/g, ' '))} · since <time className="mono">{time(r.ts, true)}</time></p></div>
        </li>)}</ul>}
        <Link to="/incident" className="inline-link">All incidents</Link>
      </Panel>
    </div>
    <Dialog open={huntOpen} title="Start a fleet hunt?" onClose={() => setHuntOpen(false)} actions={<>
      <Button variant="ghost" onClick={() => setHuntOpen(false)}>Cancel</Button><Button pending={hunt.pending} onClick={() => {setHuntOpen(false); void hunt.run('/api/fleet-hunt', {type: 'fleet_hunt', model: huntModel.trim() || 'all'});}}>Start hunt</Button>
    </>}><p>The fleet agent watches monitors of the same model for related attack patterns. IT decides whether to cut off another monitor.</p>
      <label className="field">Monitor model<input value={huntModel} onChange={e => setHuntModel(e.target.value)} maxLength={128} /></label><p className="tiny">Use “all” to watch every monitor on the ward.</p>
    </Dialog>
  </div>;
}
