import type {ChipOpinion} from '../lib/types';
import {Tip} from './ui';
import {Fact} from './extra';

// Live M2-gbt2 evaluation: docs/evidence/ML-RESULTS.md, held-out CinC score.
const LIVE_MODEL_HELDOUT_CINC = 0.862;

export function freshChipOpinion(opinion: ChipOpinion | null | undefined, now: number): ChipOpinion | null {
  return opinion && now - opinion.ts < 120_000 ? opinion : null;
}

/** Display evidence only; alarm colours and decision controls stay with the live verdict. */
export function ChipOpinionPanel({opinion, now}: {opinion: ChipOpinion | null | undefined; now: number}) {
  const fresh = freshChipOpinion(opinion, now);
  return (
    <section className="chip-opinion" aria-label="AI-chip second opinion">
      <h3 aria-label="AI-chip second opinion (IBM Telum II, on-chip)"><Tip text="A separate alarm model runs on IBM's AI chip; its result is shown for comparison only.">
        <span>AI-chip second opinion (IBM Telum II, on-chip)</span>
      </Tip></h3>
      {fresh ? <>
        <dl className="facts">
          <Fact label="Alarm" value={fresh.alarm_code} hint="The monitor alarm judged by the chip; it may differ from the current alarm." />
          <Fact label="Real-alarm probability" value={`${Math.round(fresh.p_real * 100)}%`} hint="The chip model's estimated chance that this alarm is real; it does not change the live verdict." />
          <Fact label="Label" value={fresh.label} hint={`The chip's real or false label uses its own threshold of ${fresh.threshold.toFixed(2)}.`} />
          <Fact label="Device" value={fresh.device} hint="The accelerator device that ran this second opinion." />
          <Fact label="Latency" value={`${fresh.latency_ms} ms`} hint="Inference time reported by the chip service, excluding network travel." />
        </dl>
        <Tip text={`Held-out scores measure performance on separate records, not this alarm's probability. VTaC held-out score ${fresh.heldout_challenge_vtac.toFixed(3)}. Chip model: ${fresh.model}.`}>
          <p className="tiny muted">Shown only, not used in decisions. Held-out score {fresh.heldout_challenge_cinc.toFixed(3)} (CinC) vs live model {LIVE_MODEL_HELDOUT_CINC.toFixed(3)}.</p>
        </Tip>
      </> : <Tip text="No chip result is available for this bed in the last 120 seconds; demo reset also clears it.">
        <p className="tiny muted">No alarm judged on the chip yet.</p>
      </Tip>}
    </section>
  );
}
