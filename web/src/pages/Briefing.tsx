import {useState} from 'react';
import {AlertTriangle, Check, FileText} from 'lucide-react';
import {useResource} from '../lib/hooks';
import {dateTime} from '../lib/domain';
import type {Briefing, Workload} from '../lib/types';
import {BedLink, Chip, Empty, Panel, ResourceState, SegmentedControl, Stats} from '../components/ui';
import {PageHeader} from '../components/pages/PageHeader';
import {actorName, plainText} from '../components/pages/actions';

const LIMIT = 40;
/** Workload lists nurses only: keep the API's role and older-record behavior. */
export function nursesOnly(list: Workload['nurses']) {
  return list.filter(n => n.role ? n.role === 'nurse' : !/^staff:dr_|\(Doctor\)/i.test(`${n.nurse_id} ${n.nurse_name}`));
}

export function BriefingPage() {
  const [tab, setTab] = useState<'briefing' | 'workload'>('briefing');
  const brief = useResource<Briefing>(tab === 'briefing' ? '/api/briefing' : null, 20000);
  const load = useResource<Workload>(tab === 'workload' ? '/api/workload?hours=2' : null, 20000);
  const b = brief.data;
  const f = b?.facts ?? null;
  const nurses = nursesOnly(load.data?.nurses ?? []);
  const max = Math.max(LIMIT * 1.25, ...nurses.map(n => n.alarms_last_2h));
  const blind = [...((f?.blind_time ?? b?.blind_time) ?? [])].sort((x, y) => y.minutes - x.minutes);
  const blindMax = Math.max(1, ...blind.map(x => x.minutes));
  const since = f?.since_ts ?? (b ? Date.parse(b.since) : null);
  const granite = b?.generated_by === 'IBM Granite';
  const rejected = /reject|fact.?check/i.test(b?.fallback_reason || '');
  const writer = granite ? 'Written by IBM Granite' : b?.generated_by === 'template' ? `Written by the template${rejected ? ' (Granite draft rejected by the fact check)' : ''}` : 'Writer not recorded';
  const prose = plainText(b?.summary || '').replace(/Blind time:/gi, 'Time without trusted signals:').replace(/Untrusted beds:/gi, 'Beds needing checks by hand:').replace(/Open biomed tickets:/gi, 'Open repair tickets:');
  const paragraphs = prose.split(/\n\s*\n|\s+(?=Incidents:|Beds needing checks by hand:|Open repair tickets:|Time without trusted signals:|Alerts to staff:|Loose-sensor episodes:|False alarms silenced:)/).filter(Boolean);
  return <div className="page pages-page briefing-page">
    <PageHeader title="Briefing and workload" description="A handover from the ward’s recorded facts, with each nurse’s recent alarm load.">
      <SegmentedControl label="Briefing or workload" value={tab} onChange={setTab} options={[
        {value: 'briefing', label: 'Briefing'}, {value: 'workload', label: 'Workload'},
      ]} />
    </PageHeader>
    {tab === 'briefing' ? <div className="briefing-reading">
      {brief.error && !b ? <Empty title="No briefing available" detail="The handover could not be loaded. The briefing agent publishes a summary during each run." /> :
        <ResourceState loading={brief.loading && !b} error={b ? brief.error : ''} retry={() => void brief.reload()} />}
      {b && <>
        <div className="briefing-period"><FileText size={16} aria-hidden="true" /><span>{f?.shift_start ? `Shift since ${f.shift_start}` : `Since ${since ? dateTime(since) : 'time not recorded'}`}{f?.data_from ? ` · ward data from ${f.data_from}` : ''}</span></div>
        <Stats items={[
          {label: 'Incidents', value: f?.incident_count ?? b.incidents, hint: 'Incidents counted when this briefing was written.'},
          {label: 'Not trusted', value: f?.untrusted_bed_count ?? b.untrusted_beds, hint: 'Beds without trusted readings when the briefing was written.'},
          {label: 'Open repairs', value: f?.open_ticket_count ?? b.open_tickets, hint: 'Unresolved repair tickets when the briefing was written.'},
          {label: 'Hand-check beds', value: blind.filter(x => x.minutes > 0).length, hint: 'Beds with any time without trusted readings in this period.'},
        ]} />
        <article className="briefing-paper">
          <div className="briefing-paper-head"><h2>Shift handover</h2><time className="mono">{dateTime(b.ts)}</time></div>
          <Chip className="briefing-writer">{writer}</Chip>
          <div className="summary-text">{paragraphs.length ? paragraphs.map((p, i) => <p key={i}>{p}</p>) : <p>No summary has been recorded yet.</p>}</div>
          {!granite && b.fallback_reason && <p className="briefing-source">{rejected ? 'The fact check rejected the Granite draft. This summary uses the recorded facts directly.' : /unavailable/i.test(b.fallback_reason) ? 'Template used because: Granite unavailable for this draft.' : /still writing/i.test(b.fallback_reason) ? 'The template is shown while Granite is still writing.' : 'The template wrote this summary from the ward’s recorded facts.'}</p>}
          <details className="record-details"><summary>Source details</summary><div className="record-original"><p>{f ? 'The counts and durations below come from the same record as this summary.' : 'This server did not include the summary’s source facts. Counts may differ from the prose.'}</p><pre>{JSON.stringify({generated_by: b.generated_by, fallback_reason: b.fallback_reason, facts: f}, null, 2)}</pre></div></details>
        </article>
        <Panel title="Time without trusted signals" caption="These are minutes when a monitor had no trusted readings. Check the patient by hand during these periods.">
          {!blind.length ? <p className="tiny muted">No time without trusted signals was recorded.</p> : <ul className="bars briefing-bars">{blind.map(x =>
            <li key={x.bed_id}><BedLink id={x.bed_id} /><span className="bar-track"><span className="bar-fill" style={{width: `${x.minutes / blindMax * 100}%`}} /></span><span className="mono">{x.minutes.toFixed(1)} min</span></li>)}</ul>}
        </Panel>
      </>}
    </div> : <div className="workload-reading">
      <Panel title="Alarms per nurse · last 2 hours" caption={`The marker shows ${LIMIT} alarms. Above that level, consider sharing the alarm load across the team.`}>
        <ResourceState loading={load.loading && !load.data} error={load.error} retry={() => void load.reload()} />
        {load.data && !nurses.length ? <Empty title="No recent workload record" detail="The workload agent has not published counts for the last 2 hours." /> :
          <ul className="bars workload">{nurses.map(n => {
            const over = n.alarms_last_2h > LIMIT;
            return <li key={n.nurse_id}><span className="bar-name">{actorName(n.nurse_name.replace(/\s*\(Nurse\)/i, ''))}</span>
              <span className="bar-track tall" role="img" aria-label={`${n.alarms_last_2h} alarms; reference ${LIMIT}`}><span className="bar-fill" style={{width: `${n.alarms_last_2h / max * 100}%`}} /><span className="bar-limit" style={{left: `${LIMIT / max * 100}%`}} aria-hidden="true" /></span>
              <span className="mono">{n.alarms_last_2h}</span><Chip className={over ? 'workload-over' : ''}>{over ? <AlertTriangle size={13} aria-hidden="true" /> : <Check size={13} aria-hidden="true" />}{over ? 'Consider sharing' : 'Within limit'}</Chip>
            </li>;
          })}</ul>}
      </Panel>
    </div>}
  </div>;
}
