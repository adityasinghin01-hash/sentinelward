import {ClipboardCheck} from 'lucide-react';
import {modelChecks, score01, verdictView} from '../../lib/domain';
import type {BedDetail} from '../../lib/types';
import {Panel, Tip, Trust} from '../ui';
import {ChipOpinionPanel} from '../ChipOpinion';
import {plainEvidence} from './copy';

const checkNames: Record<string, {name: string; scale: string}> = {
  M1: {name: 'Sensor usable', scale: 'Unusable signal likelihood'},
  M2: {name: 'Real emergency', scale: 'Real alarm likelihood'},
  M3: {name: 'Body match', scale: 'Signal mismatch likelihood'},
  M4: {name: 'Replay check', scale: 'Replayed data likelihood'},
  M5: {name: 'Network check', scale: 'Network attack likelihood'},
  M6: {name: 'Drift', scale: 'Pressure drift likelihood'},
};

export function WhyPanel({detail, now, explanation}: {detail: BedDetail; now: number; explanation?: string}) {
  const latest = detail.recent_verdicts[0];
  const reasons = latest?.reasons?.length ? latest.reasons : [detail.reason || 'No reason recorded'];
  const view = verdictView(detail);
  const entries = Object.entries(modelChecks);
  const available = entries.filter(([key]) => typeof detail.scores?.[key]?.score === 'number');
  const unavailable = entries.filter(([key]) => typeof detail.scores?.[key]?.score !== 'number');
  const sentence = explanation || ({
    NORMAL: 'No concern is reported by the current verdict.',
    TAMPERING: 'The monitor may have been tampered with. Its readings are not trusted.',
    DEVICE_ATTACK: 'The monitor may have been tampered with. Its readings are not trusted.',
    LOOSE_SENSOR: 'The signal suggests a loose sensor.',
    DRIFTING: 'The pressure sensor appears to be drifting.',
    UNSURE: 'The readings are unclear. Check the patient by hand.',
  } as Record<string, string>)[detail.verdict ?? ''] || view.headline;
  return <Panel title="Why SentinelWard says this" className="bed-why">
    <p className="bed-verdict-sentence">{plainEvidence(sentence)}</p>
    <ul className="bed-reasons">{reasons.map(reason => <li key={reason}>{plainEvidence(reason)}</li>)}</ul>
    <p className="bed-directive"><ClipboardCheck size={16} aria-hidden="true" />{plainEvidence(detail.requested_action || 'Continue monitoring')}</p>
    <div className="bed-checks" aria-label="Signal checks">
      {available.map(([key, meta]) => {
        const check = detail.scores[key], score = check.score!;
        return <div className="bed-check" key={key}>
          <div className="bed-check-heading"><Tip text={`${key}: ${meta.meaning}`}><b>{checkNames[key].name}</b></Tip><span className="mono">{score01(score)}</span></div>
          <div className="bed-check-track" role="meter" aria-label={`${checkNames[key].name}: ${checkNames[key].scale}`} aria-valuenow={score} aria-valuemin={0} aria-valuemax={1}>
            <span style={{width: `${Math.max(0, Math.min(1, score)) * 100}%`}} />
          </div>
          <div className="bed-check-scale">{checkNames[key].scale}</div>
          {check.reason && <p>{plainEvidence(check.reason)}</p>}
        </div>;
      })}
    </div>
    {unavailable.length > 0 && <details className="bed-disclosure bed-na-details"><summary>Details <span>{unavailable.length} checks unavailable</span></summary>
      <dl>{unavailable.map(([key]) => <div key={key}><dt>{checkNames[key].name}</dt><dd>{plainEvidence(detail.scores?.[key]?.reason || 'No score received yet')}</dd></div>)}</dl>
    </details>}
    <div className="bed-trust-line"><span>Signal trust</span><Trust bed={detail} /></div>
    <details className="bed-disclosure bed-engineering"><summary>Engineering details</summary>
      <p className="tiny muted">Each bar shows a likelihood from 0 to 1, with its meaning labelled. These scores are evidence, not a diagnosis.</p>
      <dl className="bed-model-key">{entries.map(([key]) => <div key={key}><dt>{checkNames[key].name} <small className="mono">{key}</small></dt><dd>{modelChecks[key].meaning}</dd></div>)}</dl>
      {view.alarm && <p className="tiny">{view.alarm}</p>}
      {view.aiCheck && <p className="tiny">{view.aiCheck}</p>}
      {view.why && <p className="tiny">{view.why}</p>}
      {view.showConfidence && <p className="tiny">Decision confidence: <span className="mono">{score01(latest?.confidence)}</span></p>}
      <ChipOpinionPanel opinion={detail.chip_opinion} now={now} />
    </details>
  </Panel>;
}
