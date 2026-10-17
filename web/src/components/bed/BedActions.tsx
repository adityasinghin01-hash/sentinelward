import type {Action} from '../../lib/types';
import {time} from '../../lib/domain';
import {Empty, Undo, humanName} from '../ui';
import {actionView} from '../pages/actions';

export function BedActions({actions}: {actions: Action[]}) {
  if (!actions.length) return <Empty title="No actions recorded" detail="Staff and automatic actions for this bed will appear here." />;
  return <ol className="bed-actions">
    {actions.map(action => {
      const view = actionView(action);
      return <li key={action.id}>
      <div className="bed-action-copy"><time className="mono" dateTime={new Date(action.occurred_at).toISOString()}>{time(action.occurred_at, true)}</time>
        <strong className="event-summary" title={view.summary}>{view.summary}</strong>
        <p className="tiny muted">{view.who}</p><p>{view.why}</p>
        <details className="bed-record-details"><summary>Details</summary><dl>
          <dt>Original record</dt><dd>{action.action}</dd>
          <dt>Action ID</dt><dd className="mono">{action.id}</dd>
          <dt>Action type</dt><dd className="mono">{action.action_code}</dd>
          <dt>Actor</dt><dd>{action.actor}</dd>
          <dt>Mode</dt><dd>{action.mode === 'automatic' ? 'Automatic' : 'Staff action'}</dd>
          {action.device_id && <><dt>Monitor</dt><dd className="mono">{action.device_id}</dd></>}
          {action.approved_by && <><dt>Approved by</dt><dd>{humanName(action.approved_by)}</dd></>}
          {action.references_action_id && <><dt>Related action</dt><dd className="mono">{action.references_action_id}</dd></>}
        </dl></details>
      </div>
      {action.mode === 'automatic' && action.undoable && <Undo action={action} />}
    </li>;})}
  </ol>;
}
