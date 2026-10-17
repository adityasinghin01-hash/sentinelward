import type {Action} from '../../lib/types';
import {actionView, plainText} from './actions';

/** Only formats the displayed draft; its original field values remain the save/export source until edited. */
export function reportText(value: string, bed: string, monitor: string): string {
  return value.split('\n').map(line => {
    const match = line.match(/^(?:(\d{2}:\d{2}(?::\d{2})?)\s+)?(A[1-8])\s+([\w.-]+):\s*(.*)$/);
    if (match) {
      const v = actionView({actor: match[2], action_code: match[3], action: match[4], bed_id: bed, device_id: monitor, mode: 'automatic'} as Action);
      return `${match[1] ? `${match[1]} ` : ''}${v.who}: ${v.what}. ${v.why}.`;
    }
    return plainText(line)
      .replace(/(?:\S*\/)?(?:messages|readings)\.jsonl\b/g, 'Signal record')
      .replace(/(?:\S*\/)?(?:verdicts|verdict_log)\.jsonl\b/g, 'Decision record')
      .replace(/(?:\S*\/)?timeline\.json\b/g, 'Event timeline')
      .replace(/(?:\S*\/)?network_log\.jsonl\b/g, 'Network record');
  }).join('\n');
}
