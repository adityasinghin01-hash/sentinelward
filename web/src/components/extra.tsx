import type {ReactNode} from 'react';
import {Tip} from './ui';

/** 0–1 suspicion meter for one AI check. Blue fill only: a score is evidence, not an alarm. */
export function Meter({value, label, hint}: {value: number | null | undefined; label?: string; hint: string}) {
  const ok = typeof value === 'number' && Number.isFinite(value);
  const pct = ok ? Math.max(0, Math.min(1, value)) * 100 : 0;
  return (
    <Tip text={hint}>
      <span className={`meter ${ok ? '' : 'meter-na'}`}>
        {label && <span className="meter-label">{label}</span>}
        <span className="meter-track" aria-hidden="true"><span className="meter-fill" style={{width: `${pct}%`}} /></span>
        <span className="mono meter-value">{ok ? value.toFixed(2) : 'n/a'}</span>
      </span>
    </Tip>
  );
}

/** Simple segmented tabs (a row of toggle buttons; the selected one is pressed). */
export function Tabs<T extends string>({value, options, onChange, label}: {
  value: T; options: {value: T; label: string; hint: string; count?: number}[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="tabs" role="group" aria-label={label}>
      {options.map(o => (
        <button key={o.value} className={`tab ${o.value === value ? 'is-on' : ''}`} aria-pressed={o.value === value}
                title={o.hint} onClick={() => onChange(o.value)}>
          {o.label}{o.count !== undefined && <span className="tab-count mono">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Neutral state chip (not an alarm): icon + word, navy palette. */
export function Chip({children, kind = 'neutral', hint}: {children: ReactNode; kind?: 'neutral' | 'info' | 'striped' | 'done'; hint?: string}) {
  const chip = <span className={`chip chip-${kind}`}>{children}</span>;
  return hint ? <Tip text={hint}>{chip}</Tip> : chip;
}

export {Dialog} from './ui';

/** Key / value row with an explanation of what the value means. */
export function Fact({label, value, hint}: {label: string; value: ReactNode; hint: string}) {
  return (
    <div className="fact">
      <dt><Tip text={hint}><span>{label}</span></Tip></dt>
      <dd>{value}</dd>
    </div>
  );
}
