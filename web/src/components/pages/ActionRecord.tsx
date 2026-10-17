import {useState} from 'react';
import {Bot, ShieldCheck, Undo2, UserRound} from 'lucide-react';
import {useWard} from '../../lib/store';
import {useCommand} from '../../lib/hooks';
import {time} from '../../lib/domain';
import type {Action} from '../../lib/types';
import {Button, ConfirmDialog, Empty, Feedback} from '../ui';
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

/** Keep the exact existing reversal endpoint and payload; only the presentation is local. */
export function UndoAction({action}: {action: Action}) {
  const role = useWard(s => s.session?.role);
  const cmd = useCommand();
  const [confirm, setConfirm] = useState(false);
  const allowed = role === 'it' || role === 'operator';
  const view = actionView(action);
  const cutOff = /disable_client|isolate_device/.test(action.action_code);
  return <span className="pages-undo">
    <Button size={36} variant="secondary" disabled={!allowed || !action.undoable || cmd.pending}
      hint={allowed ? 'Ask the responsible agent to reverse this action.' : 'IT security can undo this action.'}
      onClick={() => setConfirm(true)}><Undo2 size={14} aria-hidden="true" />Undo</Button>
    <ConfirmDialog open={confirm} title={cutOff ? 'Reconnect this monitor?' : 'Undo this action?'}
      bed={view.bed} monitor={action.device_id || 'Ward action'}
      consequence={cutOff ? 'The monitor may send signals to the ward again. Check that IT has verified it is safe to reconnect. This reversal is recorded in the action log.' : `Reverse “${view.what}”. The responsible agent will record the result in the action log.`}
      actionLabel={cutOff ? 'Reconnect monitor' : 'Undo action'} pending={cmd.pending} onClose={() => setConfirm(false)}
      onConfirm={() => {setConfirm(false); void cmd.run(`/api/actions/${encodeURIComponent(action.id)}/undo`, {type: 'undo_action', originalActionId: action.id, bedId: action.bed_id});}} />
    <Feedback message={cmd.feedback} failed={cmd.failed} />
  </span>;
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
