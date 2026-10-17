import {useMemo, useState} from 'react';
import {AlertTriangle, Sparkles} from 'lucide-react';
import {useResource} from '../lib/hooks';
import {dateTime, time} from '../lib/domain';
import type {Briefing, Workload} from '../lib/types';
import {BedLink, Empty, PageTitle, Panel, ResourceState, Stats, Tip} from '../components/ui';
import {Chip, Tabs} from '../components/extra';

const LIMIT = 40; // research threshold: more than 40 alarms in 2 h raises nurse workload (R7)
type Since = 'shift' | '2h' | '12h';

function sinceMs(s: Since, now: number) {
  if (s === '2h') return now - 2 * 3600_000;
  if (s === '12h') return now - 12 * 3600_000;
  const d = new Date(now); d.setHours(d.getHours() >= 8 && d.getHours() < 20 ? 8 : 20, 0, 0, 0);
  if (d.getTime() > now) d.setDate(d.getDate() - 1);
  return d.getTime();
}

export function BriefingPage() {
  const [tab, setTab] = useState<'briefing' | 'workload'>('briefing');
  const [since, setSince] = useState<Since>('shift');
  const from = useMemo(() => sinceMs(since, Date.now()), [since]);
  const brief = useResource<Briefing>(tab === 'briefing' ? `/api/briefing?since=${from}` : null, 20000);
  const load = useResource<Workload>(tab === 'workload' ? '/api/workload?hours=2' : null, 20000);
  const b = brief.data;
  const nurses = load.data?.nurses ?? [];
  const max = Math.max(LIMIT * 1.25, ...nurses.map(n => n.alarms_last_2h));
  const blind = [...(b?.blind_time ?? [])].sort((x, y) => y.minutes - x.minutes);
  const blindMax = Math.max(1, ...blind.map(x => x.minutes));
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
          <div className="row-actions">
            <Tabs label="Summary period" value={since} onChange={setSince} options={[
              {value: 'shift', label: `Since ${time(from)}`, hint: 'Since the start of this shift (08:00 or 20:00).'},
              {value: '2h', label: 'Last 2 h', hint: 'The last two hours.'},
              {value: '12h', label: 'Last 12 h', hint: 'The last twelve hours.'},
            ]} />
          </div>
          {brief.error && !b ? (
            <Empty title="No briefing yet" detail={`${brief.error.replace(/\.?$/, ".")} The briefing agent (A8) publishes one during each run.`} />
          ) : (
            <>
              <ResourceState loading={brief.loading && !b} error={b ? brief.error : ''} />
              {b && (
                <>
                  <Stats items={[
                    {label: 'Incidents', value: b.incidents, hint: 'Security incidents recorded in this period.'},
                    {label: 'Untrusted beds', value: b.untrusted_beds, hint: 'Beds whose data is not trusted right now.'},
                    {label: 'Open tickets', value: b.open_tickets, hint: 'Repair tickets not yet resolved.'},
                    {label: 'Beds with blind time', value: blind.filter(x => x.minutes > 0).length, hint: 'Beds that spent time with no trusted data in this period.'},
                  ]} />
                  <div className="split-2">
                    <Panel title="Handover summary" caption={`Written by ${b.generated_by} · ${dateTime(b.ts)} · from ${dateTime(Date.parse(b.since))}`}
                           aside={<Chip kind={b.generated_by === 'IBM Granite' ? 'info' : 'neutral'} hint={b.generated_by === 'IBM Granite' ? 'Written by the IBM Granite language model from verified facts.' : 'Written by the fallback template writer because Granite was not used for this briefing.'}>
                             <Sparkles size={12} aria-hidden="true" />{b.generated_by}</Chip>}>
                      <div className="summary-text">{b.summary || 'No summary text.'}</div>
                    </Panel>
                    <Panel title="Blind time per bed" caption="Minutes with no trusted data: the patient was watched by hand only.">
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
        <Panel title="Alarms per nurse, last 2 hours" caption={`The line marks ${LIMIT}: more than ${LIMIT} alarms in 2 hours is linked to higher workload and alarm fatigue.`}>
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
