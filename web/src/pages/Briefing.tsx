import {useState} from 'react';
import {AlertTriangle, Sparkles} from 'lucide-react';
import {useResource} from '../lib/hooks';
import {dateTime} from '../lib/domain';
import type {Briefing, Workload} from '../lib/types';
import {BedLink, Empty, PageTitle, Panel, ResourceState, Stats, Tip} from '../components/ui';
import {Chip, Tabs} from '../components/extra';

const LIMIT = 40; // research threshold: more than 40 alarms in 2 h raises nurse workload (R7)

/** Workload lists nurses only: by the API's role, else (older API) by leaving out doctor accounts. */
export function nursesOnly(list: Workload['nurses']) {
  return list.filter(n => n.role ? n.role === 'nurse' : !/^staff:dr_|\(Doctor\)/i.test(`${n.nurse_id} ${n.nurse_name}`));
}

export function BriefingPage() {
  const [tab, setTab] = useState<'briefing' | 'workload'>('briefing');
  // The newest A8 briefing. Its text and its facts are one record, so the numbers and the chart below match the text.
  const brief = useResource<Briefing>(tab === 'briefing' ? '/api/briefing' : null, 20000);
  const load = useResource<Workload>(tab === 'workload' ? '/api/workload?hours=2' : null, 20000);
  const b = brief.data;
  const f = b?.facts ?? null;
  const nurses = nursesOnly(load.data?.nurses ?? []);
  const max = Math.max(LIMIT * 1.25, ...nurses.map(n => n.alarms_last_2h));
  const blind = [...((f?.blind_time ?? b?.blind_time) ?? [])].sort((x, y) => y.minutes - x.minutes);
  const blindMax = Math.max(1, ...blind.map(x => x.minutes));
  const since = f?.since_ts ?? (b ? Date.parse(b.since) : null);
  const source = f ? 'From the briefing record: the same facts the summary was written from.'
    : 'Computed by the server for this period. This server does not send the briefing facts, so the summary text may use different counts.';
  return (
    <div className="page">
      <PageTitle eyebrow="S10 · Shift handover" title="Briefing and workload"
                 description="The handover summary written by the briefing agent (A8) and each nurse's alarm load (A7).">
        <Tabs label="Briefing or workload" value={tab} onChange={setTab} options={[
          {value: 'briefing', label: 'Briefing', hint: 'Plain-language handover summary for the shift.'},
          {value: 'workload', label: 'Workload', hint: 'Alarms each nurse received in the last 2 hours.'},
        ]} />
      </PageTitle>
      {tab === 'briefing' ? (
        <>
          {brief.error && !b ? (
            <Empty title="No briefing yet" detail={`${brief.error.replace(/\.?$/, ".")} The briefing agent (A8) publishes one during each run.`} />
          ) : (
            <>
              <ResourceState loading={brief.loading && !b} error={b ? brief.error : ''} />
              {b && (
                <>
                  <p className="tiny">{f?.shift_start ? `Shift since ${f.shift_start}` : `Since ${since ? dateTime(since) : '—'}`}{f?.data_from ? ` · ward data from ${f.data_from}` : ''} · {source}</p>
                  <Stats items={[
                    {label: 'Incidents', value: f?.incident_count ?? b.incidents, hint: `Security incidents opened in this shift. ${source}`},
                    {label: 'Untrusted beds', value: f?.untrusted_bed_count ?? b.untrusted_beds, hint: `Beds whose data was not trusted when the briefing was written. ${source}`, sub: f?.untrusted_beds?.length ? f.untrusted_beds.join(', ') : undefined},
                    {label: 'Open tickets', value: f?.open_ticket_count ?? b.open_tickets, hint: `Repair tickets not yet resolved. ${source}`},
                    {label: 'Beds with blind time', value: blind.filter(x => x.minutes > 0).length, hint: `Beds that spent time with no trusted data. ${source}`},
                  ]} />
                  <div className="split-2">
                    <Panel title="Handover summary" caption={`Written by ${b.generated_by === 'template' ? 'the template writer' : b.generated_by} · ${dateTime(b.ts)}`}
                           aside={<Chip kind={b.generated_by === 'IBM Granite' ? 'info' : 'neutral'} hint={b.generated_by === 'IBM Granite' ? 'Written by the IBM Granite language model from verified facts.' : `Written by the fallback template from the same facts${b.fallback_reason ? ` because: ${b.fallback_reason}` : ' because Granite was not used for this briefing'}.`}>
                             <Sparkles size={12} aria-hidden="true" />{b.generated_by === 'template' ? 'Template' : b.generated_by}</Chip>}>
                      <div className="summary-text">{b.summary || 'No summary text.'}</div>
                      {b.generated_by !== 'IBM Granite' && b.fallback_reason && <p className="tiny">Template used because: {b.fallback_reason}</p>}
                    </Panel>
                    <Panel title="Blind time per bed" caption={`Minutes with no trusted data: the patient was watched by hand only. ${f ? 'Same numbers as the summary.' : 'Server count for this period.'}`}>
                      {blind.length === 0 ? <p className="tiny">No blind time recorded in this period.</p> : (
                        <ul className="bars">
                          {blind.map(x => (
                            <li key={x.bed_id}><BedLink id={x.bed_id} />
                              <span className="bar-track"><span className="bar-fill striped" style={{width: `${x.minutes / blindMax * 100}%`}} /></span>
                              <span className="mono">{x.minutes.toFixed(1)} min</span></li>
                          ))}
                        </ul>
                      )}
                    </Panel>
                  </div>
                </>
              )}
            </>
          )}
        </>
      ) : (
        <Panel title="Alarms per nurse, last 2 hours" caption={`Nurses only (doctors are not counted here). The line marks ${LIMIT}: more than ${LIMIT} alarms in 2 hours is linked to higher workload and alarm fatigue.`}>
          <ResourceState loading={load.loading && !load.data} error={load.error} />
          {load.data && nurses.length === 0 ? <Empty title="No recent workload record" detail="The workload agent (A7) has not published counts for the last 2 hours." /> : (
            <ul className="bars workload">
              {nurses.map(n => {
                const over = n.alarms_last_2h > LIMIT;
                return (
                  <li key={n.nurse_id}>
                    <span className="bar-name">{n.nurse_name}</span>
                    <Tip text={`${n.alarms_last_2h} distinct alarms routed to ${n.nurse_name} in the last 2 hours.`}>
                      <span className="bar-track tall">
                        <span className="bar-fill" style={{width: `${n.alarms_last_2h / max * 100}%`}} />
                        <span className="bar-limit" style={{left: `${LIMIT / max * 100}%`}} aria-hidden="true" />
                      </span>
                    </Tip>
                    <span className="mono">{n.alarms_last_2h}</span>
                    {over ? <Chip kind="striped" hint={`Above ${LIMIT} alarms in 2 hours: consider rebalancing beds.`}><AlertTriangle size={12} aria-hidden="true" />over {LIMIT}</Chip>
                          : <Chip hint={`At or below ${LIMIT} alarms in 2 hours.`}>within limit</Chip>}
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>
      )}
    </div>
  );
}
