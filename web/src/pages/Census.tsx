import {useNavigate} from 'react-router-dom';
import {useWard} from '../lib/store';
import {useNow} from '../lib/hooks';
import {age, bedState, displayVitals, isOpenAlert, staff, time, trustView, value} from '../lib/domain';
import {BedLink, Empty, PageTitle, Panel, StateChip, Tip} from '../components/ui';
import {tileView} from '../components/ward/tile';
import type {TileGroup} from '../components/ward/tile';
const GROUP_RANK: Record<TileGroup, number> = {emergency: 0, security: 1, check: 2, nosignal: 3, maint: 4, normal: 5};

const ORDER = {high: 0, medium: 1, low: 2, none: 3} as const;

export function CensusPage() {
  const beds = useWard(s => s.beds);
  const alerts = useWard(s => s.alerts);
  const hidden = useWard(s => s.hidden);
  const now = useNow();
  const navigate = useNavigate();
  const rows = beds.map(b => ({b, s: bedState(b, now), v: displayVitals(b), t: tileView(b, alerts, now)}))
    .sort((x, y) => GROUP_RANK[x.t.group] - GROUP_RANK[y.t.group] || (x.s.untrusted ? 0 : 1) - (y.s.untrusted ? 0 : 1) || x.b.bed_id.localeCompare(y.b.bed_id));
  const untrusted = rows.filter(r => r.s.untrusted).length;
  return (
    <div className="page">
      <PageTitle eyebrow="S5 · Doctor / tele-ICU" title="Census"
                 description="Occupied beds sorted by who needs a doctor first, then by how much the data can be trusted.">

      </PageTitle>
      {untrusted > 0 && (
        <div className="notice-banner" role="status">
          {untrusted} bed{untrusted === 1 ? '’s' : 's’'} data can’t be trusted. Don’t act on {untrusted === 1 ? 'its' : 'their'} numbers without a bedside check.
        </div>
      )}
      <Panel title={`${rows.length} beds`} caption="Select a row to open the bed. Remote viewers are the ones a hacker fools, so trust is a column.">
        {rows.length === 0 ? <Empty title="No beds admitted" detail="Beds appear as soon as the ward hub reports them." /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                <th scope="col">Bed</th><th scope="col">Patient</th><th scope="col">Verdict</th>
                <th scope="col"><Tip text="Data trust 0 to 1: how likely the numbers are genuine. Striped = not trusted."><span>Trust</span></Tip></th>
                <th scope="col"><Tip text="Heart rate, beats per minute (last trusted value if untrusted)."><span>HR</span></Tip></th>
                <th scope="col"><Tip text="Blood oxygen saturation, percent."><span>SpO₂</span></Tip></th>
                <th scope="col"><Tip text="Blood pressure systolic / diastolic, mmHg."><span>BP</span></Tip></th>
                <th scope="col"><Tip text="Newest bedside check by a nurse or doctor (the referee)."><span>Last bedside check</span></Tip></th>
                <th scope="col"><Tip text="Yes when an open alert for this bed has reached ladder step 3 (all nurses + doctor)."><span>Escalated to doctor</span></Tip></th>
              </tr></thead>
              <tbody>
                {rows.map(({b, s, v, t}) => {
                  const escalated = alerts.some(a => a.bed_id === b.bed_id && isOpenAlert(a) && a.ladder_step >= 3);
                  const check = b.last_bedside_check;
                  return (
                    <tr key={b.bed_id} tabIndex={0} className={`row-tone-${t.tone}`} onClick={() => navigate(`/bed/${b.bed_id}`)}
                        onKeyDown={e => { if (e.key === 'Enter') navigate(`/bed/${b.bed_id}`); }}>
                      <td><BedLink id={b.bed_id} /></td>
                      <td>{!hidden && b.patient ? `${b.patient.initials} · ${b.patient.age ?? '—'} ${b.patient.sex ?? ''}` : 'Hidden'}</td>
                      <td><StateChip state={t.key === 'NO_SIGNAL' ? 'NO_DATA' : t.key === 'ALARM_OPEN' ? 'EMERGENCY' : t.key} />{t.reason && <span className="census-reason">{t.reason}</span>}</td>
                      <td className={`trust-word ${s.untrusted || trustView(b).value === null ? 'is-not' : ''}`} title={trustView(b).why || undefined}>{trustView(b).value === null ? 'Not trusted' : s.untrusted ? 'Checking' : 'Trusted'}</td>
                      <td className="mono big-cell">{value(v?.hr)}{s.untrusted && <span className="census-reading-age">{b.last_trusted?.captured_at ? `Last trusted · ${age(b.last_trusted.captured_at, now)} ago` : 'No trusted recording'}</span>}</td>
                      <td className="mono big-cell">{value(v?.spo2)}</td>
                      <td className="mono">{value(v?.systolic)}/{value(v?.diastolic)}</td>
                      <td>{check ? `${check.result === 'patient_ok' || check.status === 'patient_ok' ? 'OK' : 'NOT OK'} · ${time(Number(check.ts))} · ${staff(check.by)}` : '—'}</td>
                      <td>{escalated ? 'Yes' : 'No'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
