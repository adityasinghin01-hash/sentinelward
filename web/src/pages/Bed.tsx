import {useMemo, useState} from 'react';
import {ActionFeed} from '../components/pages/ActionRecord';
import type {FormEvent} from 'react';
import {Link, useParams} from 'react-router-dom';
import {ArrowLeft, Check, ChevronsUp, HeartPulse, Network, PhoneCall, X} from 'lucide-react';
import {useWard} from '../lib/store';
import {useCommand, useNow, useResource} from '../lib/hooks';
import {age, bedState, can, displayVitals, staff, time, value, verdictTrust, verdictView, verdictWords} from '../lib/domain';
import type {BedDetail, HistoryPoint} from '../lib/types';
import {Button, Empty, Feedback, Panel, ResourceState, Tip, Trust} from '../components/ui';
import {tileView, vitalFlags} from '../components/ward/tile';
import {AlertTriangle as BandAlert, ShieldAlert as BandShield, Activity as BandActivity, Unplug as BandUnplug, Circle as BandCircle} from 'lucide-react';
import {Chip, Fact} from '../components/extra';
import {Waveform} from '../components/Waveform';
import {TrendChart} from '../components/Chart';
import {WhyPanel} from '../components/bed/WhyPanel';
import {plainEvidence} from '../components/bed/copy';

const CHECK_EVERY_MS = 5 * 60_000; // suggested hand-check interval for an untrusted bed (R8 S3)

function num(v: unknown) { return typeof v === 'number' && Number.isFinite(v) ? v : null; }

function Witnesses({detail}: {detail: BedDetail}) {
  const m3 = detail.scores?.M3?.extra ?? {};
  const m5 = detail.scores?.M5?.extra ?? {};
  const f = (m5.features as Record<string, unknown>) ?? {};
  const pat = num(m3.pat_ms), base = num(m3.baseline_pat_ms);
  const ecgRate = num(m3.ecg_rate_bpm), ppgRate = num(m3.ppg_rate_bpm);
  const rate = num(f.msg_rate), gaps = num(f.seq_gap_count), dups = num(f.seq_dup_count);
  return (
    <Panel title="Body and network check" caption="We compare the heartbeat with the finger pulse, then check how the monitor sends its data.">
      <div className="witness-grid">
        <div className="witness">
          <h3><HeartPulse size={14} aria-hidden="true" /> Body</h3>
          <dl className="facts">
            <Fact label="Beat → pulse delay" hint="Time from the heartbeat (ECG) to the pulse arriving at the finger (pleth). A real body keeps it steady."
                  value={pat === null ? '—' : `${Math.round(pat)} ms${base !== null ? ` (usual ${Math.round(base)})` : ''}`} />
            <Fact label="Heart vs pulse rate" hint="Rate counted from the ECG versus from the finger pulse. They should agree."
                  value={ecgRate === null ? '—' : `${Math.round(ecgRate)} / ${ppgRate === null ? '—' : Math.round(ppgRate)} bpm`} />
            <Fact label="Finding" hint="Plain summary from the body-mismatch check (M3)." value={plainEvidence(detail.scores?.M3?.reason || 'No score yet')} />
          </dl>
        </div>
        <div className="witness">
          <h3><Network size={14} aria-hidden="true" /> Network</h3>
          <dl className="facts">
            <Fact label="Message rate" hint="Messages per second from this monitor. A healthy monitor sends about 1 per second."
                  value={rate === null ? '—' : `${rate.toFixed(1)}/s`} />
            <Fact label="Sequence gaps / repeats" hint="Missing or repeated message numbers. Repeats can mean old data is being replayed."
                  value={`${gaps === null ? '—' : gaps} / ${dups === null ? '—' : dups}`} />
            <Fact label="Device link" hint="Whether the hub hears this monitor now, and whether its data has been flagged."
                  value={detail.device?.isolated ? 'Data untrusted · device flagged' : detail.device?.online ? 'Online' : 'Not heard'} />
            <Fact label="Finding" hint="Plain summary from the network check (M5)." value={plainEvidence(detail.scores?.M5?.reason || 'No score yet')} />
          </dl>
        </div>
      </div>
    </Panel>
  );
}

function BedsidePanel({detail, untrusted}: {detail: BedDetail; untrusted: boolean}) {
  const role = useWard(s => s.session?.role);
  const now = useNow();
  const check = useCommand();
  const manual = useCommand();
  const [hr, setHr] = useState('');
  const [spo2, setSpo2] = useState('');
  const [notes, setNotes] = useState('');
  const allowed = can(role, 'clinical');
  const bed = detail.bed_id;
  const lastCheck = detail.last_bedside_check;
  const lastHand = Math.max(Number(lastCheck?.ts) || 0, Number(detail.manual?.ts) || 0) || null;
  const due = (lastHand ?? detail.last_trusted?.captured_at ?? now) + CHECK_EVERY_MS;
  const left = due - now;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = {type: 'record_manual_reading', bedId: bed, notes};
    if (hr.trim()) body.heartRate = Number(hr);
    if (spo2.trim()) body.spo2 = Number(spo2);
    if (await manual.run(`/api/beds/${encodeURIComponent(bed)}/manual-reading`, body)) { setHr(''); setSpo2(''); setNotes(''); }
  };
  const noValue = !hr.trim() && !spo2.trim();
  return (
    <Panel title="Bedside check" caption="The nurse at the bed decides. The result is logged and shown on the ward screen.">
      <div className="bedside-row">
        <span>Checked the patient at the bedside?</span>
        <Button variant="secondary" pending={check.pending} disabled={!allowed} title={allowed ? 'Record that the patient is fine on direct check.' : 'Only nurses and doctors record bedside checks.'}
                onClick={() => void check.run(`/api/beds/${encodeURIComponent(bed)}/bedside-check`, {type: 'confirm_bedside', bedId: bed, status: 'patient_ok'})}>
          <Check size={14} aria-hidden="true" /> Patient OK
        </Button>
        <Button variant="danger" pending={check.pending} disabled={!allowed} title={allowed ? 'Record that the patient is NOT fine: escalate care now.' : 'Only nurses and doctors record bedside checks.'}
                onClick={() => void check.run(`/api/beds/${encodeURIComponent(bed)}/bedside-check`, {type: 'confirm_bedside', bedId: bed, status: 'patient_not_ok'})}>
          <X size={14} aria-hidden="true" /> Patient NOT OK
        </Button>
      </div>
      <p className="tiny">
        Last bedside check: {lastCheck ? `${lastCheck.result === 'patient_ok' || lastCheck.status === 'patient_ok' ? 'Patient OK' : 'Patient NOT OK'} · ${time(Number(lastCheck.ts))} by ${staff(lastCheck.by)}` : 'none recorded'}
      </p>
      <Feedback message={check.feedback} failed={check.failed} />
      {untrusted && (
        <div className="manual-check">
          <div className="manual-head">
            <strong>Check pulse and breathing by hand</strong>
            <Tip text="Suggested interval between hand checks while this monitor is not trusted (5 minutes).">
              <span className="mono">{left > 0 ? `next check in ${Math.floor(left / 60000)}:${String(Math.floor(left % 60000 / 1000)).padStart(2, '0')}` : 'hand check due now'}</span>
            </Tip>
          </div>
        </div>
      )}
      <form className="manual-form" onSubmit={e => void submit(e)}>
        <label>HR <small>bpm</small><input inputMode="numeric" value={hr} onChange={e => setHr(e.target.value.replace(/[^\d.]/g, ''))} aria-describedby="manual-hint" /></label>
        <label>SpO₂ <small>%</small><input inputMode="numeric" value={spo2} onChange={e => setSpo2(e.target.value.replace(/[^\d.]/g, ''))} /></label>
        <label className="grow">Notes<input value={notes} maxLength={400} onChange={e => setNotes(e.target.value)} placeholder="e.g. radial pulse, portable oximeter" /></label>
        <Button type="submit" pending={manual.pending} disabled={!allowed || noValue}
                title={!allowed ? 'Only nurses and doctors record hand checks.' : noValue ? 'Enter at least one value.' : 'Save this hand check to the bed record.'}>
          Record hand check
        </Button>
      </form>
      <p className="tiny" id="manual-hint">Hand-check values are kept separately from monitor data
        {detail.manual ? ` · last: HR ${value(detail.manual.hr)}, SpO₂ ${value(detail.manual.spo2)} at ${time(Number(detail.manual.ts))}` : ''}.</p>
      <Feedback message={manual.feedback} failed={manual.failed} />
    </Panel>
  );
}

export function BedPage() {
  const {bedId = ''} = useParams();
  const role = useWard(s => s.session?.role);
  const liveBed = useWard(s => s.beds.find(b => b.bed_id === bedId));
  const actions = useWard(s => s.actions);
  const alerts = useWard(s => s.alerts);
  const hidden = useWard(s => s.hidden);
  const now = useNow();
  const res = useResource<BedDetail>(`/api/beds/${encodeURIComponent(bedId)}`, 3000);
  const hist = useResource<{points: HistoryPoint[]}>(`/api/beds/${encodeURIComponent(bedId)}/history?minutes=30`, 15000);
  const alertCmd = useCommand();
  const callCmd = useCommand();

  // Live tile fields (WebSocket) win over the polled detail; scores and verdict history come from the detail.
  const detail = useMemo(() => (res.data ? {...res.data, ...(liveBed ?? {})} as BedDetail : null), [res.data, liveBed]);
  const trend = useMemo(() => {
    const p = hist.data?.points ?? [];
    return {
      ts: p.map(x => x.ts), untrusted: p.map(x => !x.trusted),
      series: [
        {label: 'HR', unit: 'bpm', color: 'var(--wave-ecg)', values: p.map(x => x.hr)},
        {label: 'SpO₂', unit: '%', color: 'var(--wave-pleth)', values: p.map(x => x.spo2)},
        {label: 'BP sys', unit: 'mmHg', color: 'var(--wave-abp)', values: p.map(x => x.sys ?? x.abp_mean ?? null)},
      ],
      rr: [...p].reverse().find(x => typeof x.rr === 'number')?.rr ?? null,
    };
  }, [hist.data]);

  if (!detail) {
    if (res.error && !res.loading) {
      return (
        <div className="page">
          <Empty title={`Bed ${bedId} not available`} detail={res.error}>
            <Link to="/ward" className="button-link">Back to Ward</Link>
          </Empty>
        </div>
      );
    }
    return <div className="page"><div className="skeleton-block" aria-busy="true">Loading bed {bedId}…</div></div>;
  }

  const state = bedState(detail, now);
  const v = displayVitals(detail);
  const wave = state.untrusted && detail.last_trusted ? detail.last_trusted.waveform : detail.waveform;
  // The bed's own open alert, else the newest open one for this bed from the live alert list.
  const openAlert = detail.open_alerts?.[0] ?? alerts.find(a => a.bed_id === bedId && (a.status === 'open' || a.status === 'escalated'));
  const clinical = can(role, 'clinical');
  const bedActions = actions.filter(a => a.bed_id === bedId || a.device_id === detail.device_id).slice(0, 10);
  const frozenAt = detail.last_trusted?.captured_at;
  const flags = vitalFlags(detail);
  const tv = tileView(detail, alerts, now);
  const vv = verdictView(detail);
  const cause = tv.key === 'ALARM_OPEN' ? 'An emergency alert is open on this bed. Go now and check the patient by hand.'
    : tv.group === 'emergency' ? vv.headline.replace(' — ', '. ').replace(/^./, c => c.toUpperCase())
    : tv.key === 'UNSURE' ? `The checks disagree, so the patient must be checked by hand.${vv.why ? ' ' + vv.why.replace(/^Blocked by: /, 'Reason: ') : ''}`
    : tv.reason || 'All checks agree. Keep monitoring.';
  const BandIcon = tv.tone === 'ok' ? BandCircle : tv.tone === 'security' || tv.tone === 'both' ? BandShield : tv.tone === 'maint' ? BandActivity : tv.tone === 'nodata' ? BandUnplug : BandAlert;

  return (
    <div className="page bed-page">
      <div className={`bed-header tone-${tv.tone}`}>
        <div className="bed-head-row">
        <Link to="/ward" className="back" title="Back to all beds"><ArrowLeft size={16} aria-hidden="true" /> Ward</Link>
        <h1>Bed {detail.bed_id.replace(/^B0?/, '')}</h1>
        <span className="patient">{!hidden && detail.patient ? `${detail.patient.initials} · ${detail.patient.age ?? '—'} ${detail.patient.sex ?? ''}` : ''}</span>
        <Tip text="Monitor ID, as the IT security screen shows it."><span className="mono muted">{detail.device_id}</span></Tip>
        <div className="bed-header-actions">

          <button className="button-primary" disabled={!clinical || !openAlert || alertCmd.pending}
                  title={!clinical ? 'Only nurses and doctors acknowledge alerts.' : !openAlert ? 'No open alert on this bed.' : 'I am on it: stops the escalation ladder.'}
                  onClick={() => openAlert && void alertCmd.run(`/api/alerts/${encodeURIComponent(openAlert.alert_id)}/ack`, {})}>
            <Check size={14} aria-hidden="true" /> Acknowledge
          </button>
          <button disabled={!clinical || !openAlert || alertCmd.pending}
                  title={!clinical ? 'Only nurses and doctors escalate alerts.' : !openAlert ? 'No open alert on this bed.' : 'Send this alert to the next step now (next nurse, then all nurses and the doctor).'}
                  onClick={() => openAlert && void alertCmd.run(`/api/alerts/${encodeURIComponent(openAlert.alert_id)}/escalate`, {type: 'escalate_alert', alertId: openAlert.alert_id, bedId})}>
            <ChevronsUp size={14} aria-hidden="true" /> Escalate
          </button>
          {role === 'doctor' && (
            <button disabled={callCmd.pending} title="Ping the bedside nurse to go to this bed (shown on their screen)."
                    onClick={() => void callCmd.run(`/api/beds/${encodeURIComponent(bedId)}/call-nurse`, {type: 'call_bedside_nurse', bedId, urgency: 'urgent'})}>
              <PhoneCall size={14} aria-hidden="true" /> Call bedside nurse
            </button>
          )}
        </div>
        </div>
        <div className="bed-band" role={tv.group === 'emergency' ? 'alert' : undefined}>
          <BandIcon size={18} aria-hidden="true" />
          <b>{tv.word}</b>
          <span className="bed-cause">{cause}</span>
          {tv.footer && !/cut off/i.test(tv.reason) && <span className="bed-band-foot">{tv.footer}</span>}
        </div>
      </div>
      <Feedback message={alertCmd.feedback || callCmd.feedback} failed={alertCmd.failed || callCmd.failed} />
      <ResourceState loading={false} error={res.error} retry={() => void res.reload()} />

      <div className="bed-layout">
        <div className="bed-main">
          <Panel title={state.untrusted ? 'Last trusted signals' : 'Live signals'}
                 caption={state.untrusted ? `Frozen at the newest trusted recording${frozenAt ? ` · ${time(frozenAt, true)}` : ''}` : 'Most recent samples from the monitor, about 25 per second.'}
                 aside={<Trust bed={detail} />} className={`bed-signals ${state.untrusted ? 'untrusted-panel' : ''}`}>
            {state.untrusted && (
              <div className="last-good big">Not trusted · showing the last good recording{frozenAt ? ` from ${time(frozenAt, true)} (${age(frozenAt, now)} ago)` : ' (none yet: check by hand)'}</div>
            )}
            {state.offline && <div className="data-age">No signal · {detail.last_updated_at ? `${age(detail.last_updated_at, now)} since the last reading` : 'nothing received yet'}</div>}
            <div role="group" aria-label="Vital signs" className={`big-vitals ${state.untrusted || state.offline ? 'greyed' : ''} tone-text-${state.tone}`}>
              <Tip text="Heart rate in beats per minute. A dash means no reading; zero is a real measurement."><div className={`vital ${flags.hr ? 'outside-limit' : ''}`}><span>HR <small>bpm</small></span><strong>{value(v?.hr)}{flags.hr && <i className="bed-vital-arrow" title="Outside alert limits">{flags.hr === 'high' ? '↑' : '↓'}</i>}</strong></div></Tip>
              <Tip text="Blood oxygen saturation from the finger sensor, in percent."><div className={`vital ${flags.spo2 ? 'outside-limit' : ''}`}><span>SpO₂ <small>%</small></span><strong>{value(v?.spo2)}{flags.spo2 && <i className="bed-vital-arrow" title="Outside alert limits">↓</i>}</strong></div></Tip>
              <Tip text="Blood pressure, systolic / diastolic in mmHg."><div className={`vital bp ${flags.sys ? 'outside-limit' : ''}`}><span>BP <small>mmHg</small></span><strong>{value(v?.systolic)}<span>/</span>{value(v?.diastolic)}{flags.sys && <i className="bed-vital-arrow" title="Outside alert limits">{flags.sys === 'high' ? '↑' : '↓'}</i>}</strong></div></Tip>
              <Tip text="Breathing rate in breaths per minute, newest value in the 30-minute history."><div className="vital rr"><span>RR <small>/min</small></span><strong>{value(trend.rr)}</strong></div></Tip>
            </div>
            <Waveform samples={wave?.ecg || []} large frozen={state.untrusted || state.offline} />
            <Waveform samples={wave?.ppg || []} label="PLETH" large frozen={state.untrusted || state.offline} />
            {state.untrusted && detail.vitals && (
              <div className="incoming" title="What the monitor is sending now. Not trusted: do not act on these numbers.">
                <span className="eyebrow">Incoming (not trusted)</span>
                <span className="mono">HR {value(detail.vitals.hr)} · SpO₂ {value(detail.vitals.spo2)} · BP {value(detail.vitals.systolic)}/{value(detail.vitals.diastolic)}</span>
              </div>
            )}
          </Panel>
          <Panel title="30-minute trend" caption="Each signal has its own scale. Shaded periods are not trusted." className="bed-trends"
                 aside={<span className="bed-meta mono">5 min intervals</span>}>
            <TrendChart ts={trend.ts} series={trend.series} untrusted={trend.untrusted} label={`30-minute trend of heart rate, SpO2 and blood pressure for ${bedId}`} />
            {hist.error && <p className="tiny">History unavailable: {hist.error}</p>}
          </Panel>
          <BedsidePanel detail={detail} untrusted={state.untrusted || detail.verdict === 'UNSURE'} />
          <Witnesses detail={detail} />
        </div>
        <aside className="bed-side">
          <WhyPanel detail={detail} now={now} explanation={tv.key === 'ALARM_OPEN' ? cause : undefined} />
          <Panel title="Recent verdicts" caption="Newest first · checked about every 5 seconds" className="bed-verdicts">
            {detail.recent_verdicts.length === 0 ? <p className="tiny">No verdicts received yet.</p> : (
              <ol className="verdict-list">
                {detail.recent_verdicts.slice(0, 6).map((r, i) => (
                  <li key={`${r.ts}-${i}`}><time className="mono">{time(r.ts, true)}</time><span>{plainEvidence(verdictWords[r.verdict] ?? r.verdict)}</span>
                    <Tip text="Data trust attached to this verdict, 0 to 1. Verdicts made after the device was flagged or went silent show “not trusted”."><span className="bed-history-trust">{verdictTrust(r.trust, r.ts, detail) === 'not trusted' ? 'Not trusted' : r.trust == null ? 'Checking' : r.trust >= .5 ? 'Trusted' : 'Checking'}</span></Tip></li>
                ))}
              </ol>
            )}
          </Panel>
          <Panel title="Actions for this bed" caption="Who acted, and why. IT security can undo automatic actions." className="bed-action-panel">
            <ActionFeed actions={bedActions} emptyTitle="No actions for this bed yet" />
          </Panel>
          {detail.assignment && (
            <Panel title="Assignment">
              <p className="tiny">Assigned to {staff(detail.assignment.staff_id ?? detail.assignment.clinician_id)} · status {String(detail.assignment.status ?? '—').replace(/_/g, ' ')}</p>
              {detail.nurse_call && <Chip kind="info" hint="A doctor asked the bedside nurse to go to this bed.">Nurse called · {time(Number(detail.nurse_call.ts))}</Chip>}
            </Panel>
          )}
        </aside>
      </div>
    </div>
  );
}
