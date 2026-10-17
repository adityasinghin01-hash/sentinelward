import type {ChipOpinion} from './types';

export function freshChipOpinion(opinion: ChipOpinion | null | undefined, now: number): ChipOpinion | null {
  return opinion && now - opinion.ts < 120_000 ? opinion : null;
}
