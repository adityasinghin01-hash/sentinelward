import type {Action} from '../../lib/types';
import {time} from '../../lib/domain';
import {Empty, Undo, humanName} from '../ui';
import {plainEvidence} from './copy';

function actionSentence(action: Action) {
  const who = humanName(action.actor);
  if (action.action_code === 'hash_file') {
    const kind = /messages\.jsonl/.test(action.action) ? 'messages' : /verdicts\.jsonl/.test(action.action) ? 'verdicts' : /timeline\.json/.test(action.action) ? 'timeline' : 'evidence';
    return `${who} recorded a fingerprint of the captured ${kind}.`;
  }
  if (action.action_code === 'disable_client') {
    const why = action.action.match(/after (.+?)(?:;|$)/)?.[1];
    return `${who} cut off the monitor${why ? ` after ${plainEvidence(why)}` : ''}.`;
  }
  const text = plainEvidence(action.action)
    .replace(/\b(?:[a-z]+_)?[a-f0-9]{64}\b/gi, '[fingerprint in Details]')
    .replace(/(?:\b[\w.-]+\/)*[\w.-]+\.(?:jsonl?|csv|zip|pdf)\b/gi, 'evidence file');
  return `${who}: ${text}`;
}

export function BedActions({actions}: {actions: Action[]}) {
  if (!actions.length) return <Empty title="No actions recorded" detail="Staff and automatic actions for this bed will appear here." />;
  return <ol className="bed-actions">
    {actions.map(action => <li key={action.id}>
      <div className="bed-action-copy"><time className="mono" dateTime={new Date(action.occurred_at).toISOString()}>{time(action.occurred_at, true)}</time>
        <p>{actionSentence(action)}</p>
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
    </li>)}
  </ol>;
}
