import {Bot, ShieldCheck, UserRound} from 'lucide-react';
import {time} from '../../lib/domain';
import type {Action} from '../../lib/types';
import {Empty, Undo} from '../ui';
import {actionView} from './actions';
import type {ActorKind} from './actions';

export function ActorIcon({kind}: {kind: ActorKind}) {
  const Icon = kind === 'agents' ? Bot : kind === 'it' ? ShieldCheck : UserRound;
  return <Icon size={16} aria-hidden="true" />;
}

export function ActionDetails({action}: {action: Action}) {
  return <details className="record-details"><summary>Details</summary>
    <div className="record-original"><p>Original audit record</p><pre>{JSON.stringify(action, null, 2)}</pre></div>
  </details>;
}

/** One confirmation and result message for every action log. */
export function UndoAction({action}: {action: Action}) {
  return <Undo action={action} />;
}

export function ActionFeed({actions, emptyTitle = 'No actions recorded'}: {actions: Action[]; emptyTitle?: string}) {
  if (!actions.length) return <Empty title={emptyTitle} detail="Recorded actions will appear here with who acted and why." />;
  return <ol className="pages-action-feed">{actions.map(a => {
    const v = actionView(a);
    return <li key={a.id}>
      <span className={`actor-icon actor-${v.kind}`}><ActorIcon kind={v.kind} /></span>
      <div className="feed-copy"><strong>{v.what}</strong><p>{v.who} · {v.bed} · <time className="mono">{time(a.occurred_at, true)}</time></p>
        <p>{v.why}</p><ActionDetails action={a} /></div>
      {a.mode === 'automatic' && a.undoable && <UndoAction action={a} />}
    </li>;
  })}</ol>;
}
