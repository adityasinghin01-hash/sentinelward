import type {Action} from '../../lib/types';
import {actionView, actorName, plainText} from './actions';

export interface TimelineView {ts: number; what: string; who: string; why: string; kind: 'agent' | 'staff' | 'verdict'; raw: Record<string, unknown>}
/** Preserve the event verbatim while translating its agent command into the action-log vocabulary. */
export function timelineView(t: Record<string, unknown>, bed: string, monitor: string): TimelineView {
  const event = String(t.event ?? t.action ?? '');
  const match = event.match(/^(A[1-8])\s+([\w.-]+):\s*(.*)$/);
  const base = {ts: Number(t.ts), raw: t};
  if (match) {
    const v = actionView({actor: match[1], action_code: match[2], action: match[3], bed_id: bed, device_id: monitor, mode: 'automatic'} as Action);
    return {...base, what: v.what, who: v.who, why: v.why, kind: 'agent'};
  }
  if (/^Detected:/i.test(event)) {
    const state = /BOTH/.test(event) ? 'an emergency on a hacked monitor' : /TAMPERING|DEVICE_ATTACK/.test(event) ? 'a hacked monitor' : /EMERGENCY/.test(event) ? 'a possible patient emergency' : 'a change in the signal';
    return {...base, what: `Detected ${state}`, who: 'Signal checks', why: '', kind: 'verdict'};
  }
  if (/^Last trusted/i.test(event)) return {...base, what: 'Last trusted signal received', who: 'Signal checks', why: '', kind: 'verdict'};
  if (/^Alert .*open/i.test(event)) return {...base, what: `Opened the alert${event.match(/step\s*(\d)/i) ? ` · step ${event.match(/step\s*(\d)/i)![1]} of 3` : ''}`, who: 'Alert agent', why: 'Bed needs attention', kind: 'agent'};
  if (/^Bedside/i.test(event)) return {...base, what: `Patient checked: ${/patient_not_ok/.test(event) ? 'needs attention' : /patient_ok/.test(event) ? 'patient OK' : 'result recorded'}`, who: event.match(/by\s+(\S+)/)?.[1] ? actorName(event.match(/by\s+(\S+)/)![1]) : 'Staff member', why: 'Checked in person', kind: 'staff'};
  const actor = String(t.agent ?? t.by ?? 'Signal checks');
  const kind = /^A[1-8]$/.test(actor) ? 'agent' : actor.startsWith('staff:') ? 'staff' : 'verdict';
  const legacyCode = String(t.action_code ?? t.kind ?? event);
  if (!t.verdict && (kind === 'agent' || kind === 'staff')) {
    const view = actionView({actor, action_code: legacyCode, action: event, bed_id: bed, device_id: monitor, mode: kind === 'agent' ? 'automatic' : 'person'} as Action);
    if (view.what !== 'Recorded an action') return {...base, what: view.what, who: view.who, why: view.why, kind};
  }
  return {...base, what: plainText(event || (t.verdict ? `Decision: ${t.verdict}` : String(t.kind ?? 'Event recorded').replace(/_/g, ' '))), who: actor === 'Signal checks' ? actor : actorName(actor), why: '', kind};
}
