import {useEffect, useId, useRef} from 'react';
import type {ReactNode} from 'react';
import {X} from 'lucide-react';
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

/** Modal dialog for confirmations. Escape or Cancel closes; focus moves into the dialog. */
export function Dialog({open, title, children, onClose, actions}: {
  open: boolean; title: string; children: ReactNode; onClose: () => void; actions: ReactNode;
}) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>('input, textarea, select, button:not(.dialog-x)')?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('keydown', onKey); previous?.focus?.(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="dialog-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={id} ref={box}>
        <div className="dialog-head">
          <h2 id={id}>{title}</h2>
          <button className="icon-button dialog-x" onClick={onClose} title="Close without doing anything">
            <X size={16} aria-hidden="true" /><span className="sr-only">Close</span>
          </button>
        </div>
        <div className="dialog-body">{children}</div>
        <div className="dialog-actions">{actions}</div>
      </div>
    </div>
  );
}

/** Key / value row with an explanation of what the value means. */
export function Fact({label, value, hint}: {label: string; value: ReactNode; hint: string}) {
  return (
    <div className="fact">
      <dt><Tip text={hint}><span>{label}</span></Tip></dt>
      <dd>{value}</dd>
    </div>
  );
}
