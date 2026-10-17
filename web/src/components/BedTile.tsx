import {Link} from 'react-router-dom';
import {AlertTriangle, ShieldAlert, Activity, Wrench, Unplug, Circle, Ban, Cpu, ArrowUp, ArrowDown} from 'lucide-react';
import type {Alert, Bed} from '../lib/types';
import {displayVitals, value} from '../lib/domain';
import {Waveform} from './Waveform';
import {freshChipOpinion} from './ChipOpinion';
import {tileView, vitalFlags} from './ward/tile';

const ICONS = {emergency: AlertTriangle, both: ShieldAlert, security: ShieldAlert, check: AlertTriangle, maint: Activity, nodata: Unplug, ok: Circle};

function Flag({dir}: {dir: 'high' | 'low' | null}) {
  if (!dir) return null;
  const Icon = dir === 'high' ? ArrowUp : ArrowDown;
  return <Icon className="vflag" size={13} aria-label={dir === 'high' ? 'above alert limit' : 'below alert limit'} />;
}

export function BedTile({bed, hidden = true, now, mini = false, alerts = []}: {bed: Bed; hidden?: boolean; now: number; mini?: boolean; alerts?: Alert[]}) {
  const t = tileView(bed, alerts, now);
  const v = displayVitals(bed);
  const f = vitalFlags(bed);
  const frozen = t.untrusted || t.offline;
  const wave = t.untrusted && bed.last_trusted ? bed.last_trusted.waveform : bed.waveform;
  const Icon = bed.verdict === 'LOOSE_SENSOR' ? Wrench : ICONS[t.tone];
  const patient = !hidden && bed.patient ? `${bed.patient.initials} · ${bed.patient.age ?? '—'} ${bed.patient.sex ?? ''}` : '';
  return (
    <article className={`tile tone-${t.tone} ${t.untrusted ? 'is-untrusted' : ''} ${t.offline ? 'is-offline' : ''}`} data-state={t.key} data-group={t.group}>
      <Link className="tile-link" to={mini ? '/login' : `/bed/${bed.bed_id}`} aria-label={`${bed.bed_id}: ${t.word}${t.reason ? '. ' + t.reason : ''}. Open bed.`}>
        <div className="tile-band">
          <Icon size={15} aria-hidden="true" className="band-icon" />
          <span className="band-word">{t.word}</span>
          {freshChipOpinion(bed.chip_opinion, now) && <Cpu size={13} className="band-chip" aria-label="AI-chip second opinion available" />}
        </div>
        <div className="tile-body">
          <div className="tile-id">
            <span className="tile-bed">{bed.bed_id}</span>
            <span className="tile-dev mono">{bed.device_id}</span>
            {patient && <span className="tile-patient">{patient}</span>}
            {bed.isolated && <span className="tile-cut"><Ban size={11} aria-hidden="true" />Cut off</span>}
          </div>
          <div className="tile-wave">
            <Waveform samples={wave?.ecg || []} frozen={frozen} label="ECG" />
            <Waveform samples={wave?.ppg || []} frozen={frozen} label="PLETH" />
          </div>
          <div className="tile-vitals mono" aria-label="Vital signs">
            <span className={`tv tv-hr ${f.hr ? 'out' : ''}`}><small>HR</small><b>{value(v?.hr)}</b><Flag dir={f.hr} /></span>
            <span className={`tv tv-spo2 ${f.spo2 ? 'out' : ''}`}><small>SpO₂</small><b>{value(v?.spo2)}</b><Flag dir={f.spo2} /></span>
            <span className={`tv tv-bp ${f.sys ? 'out' : ''}`}><small>BP</small><b>{value(v?.systolic)}<i>/</i>{value(v?.diastolic)}</b><Flag dir={f.sys} /></span>
          </div>
          {t.reason && <p className="tile-reason">{t.reason}</p>}
          {t.footer && <p className="tile-footer">{t.footer}</p>}
        </div>
      </Link>
    </article>
  );
}
