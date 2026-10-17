import type {Action} from '../../lib/types';

export type ActorKind = 'agents' | 'people' | 'it';
export interface ActionView {who: string; kind: ActorKind; what: string; bed: string; why: string; summary: string}
const AGENTS: Record<string, string> = {
  A1: 'Alert agent', A2: 'Network agent', A3: 'Evidence agent', A4: 'Fleet agent',
  A5: 'Report agent', A6: 'Repair agent', A7: 'Workload agent', A8: 'Briefing agent',
};
const isIT = (actor: string) => /^(?:staff:)?(?:it|it_security|security|sam)$/i.test(actor);
export function actorName(actor: string): string {
  if (AGENTS[actor]) return AGENTS[actor];
  if (/^(?:staff:)?sam$/i.test(actor)) return 'Sam';
  if (isIT(actor)) return 'IT security';
  if (actor === 'system') return 'Ward service';
  if (/^(operator|demo_operator)$/i.test(actor.replace(/^staff:/, ''))) return 'Demo operator';
  const name = actor.replace(/^staff:/, '').replace(/_/g, ' ');
  return /^[\p{L} .'-]+$/u.test(name) ? name.replace(/\b\w/g, c => c.toUpperCase()) : 'Staff member';
}

/** Presentation only: the original record is never changed and remains available in Details. */
export function actionView(a: Action): ActionView {
  const raw = a.action;
  const code = a.action_code.toLowerCase();
  const who = actorName(a.actor);
  const kind: ActorKind = isIT(a.actor) ? 'it' : /^A\d+$/.test(a.actor) || a.mode === 'automatic' ? 'agents' : 'people';
  let what = 'Recorded an action';
  let why = 'Reason not recorded · see Details';
  let sentence: string | undefined;
  const monitor = a.device_id || raw.match(/\bMON-\d+\b/)?.[0] || 'the monitor';
  // The first verdict describes this event; later verdict words can describe policy, not what happened.
  const verdict = raw.match(/\b(BOTH|TAMPERING|DEVICE_ATTACK|EMERGENCY)\b/)?.[1];
  const securityReason = verdict === 'BOTH' ? 'Emergency on a hacked monitor' : verdict === 'TAMPERING' || verdict === 'DEVICE_ATTACK' ? 'Monitor may be hacked' : /attack/i.test(raw) ? 'Monitor may be hacked' : null;
  switch (code) {
    case 'send_message': case 'escalate_alert': case 'escalate': {
      const recipients = raw.match(/->\s*([^;]+)/)?.[1];
      const step = raw.match(/step\s*(\d)/i)?.[1];
      const names = recipients && !/^same people$/i.test(recipients.trim())
        ? recipients.split(/,|\s+and\s+/).map(s => actorName(s.trim())).join(', ') : null;
      if (names) {
        what = `Paged ${names}${step ? ` (step ${step})` : ''}`;
      } else what = /IT/i.test(raw) ? 'Notified IT security' : 'Sent a bedside alert';
      const wait = raw.match(/no acknowledgement for (\d+)\s*s/i)?.[1];
      if (recipients) {
        const queued = raw.match(/telegram queued for ([^;]+)/i)?.[1];
        const missing = raw.match(/no chat for ([^;]+)/i)?.[1];
        const displayNames = (list: string) => list.split(',').map(name => actorName(name.trim())).join(', ');
        let response = names ? `alert for ${names}` : `alert escalated${step ? ` to step ${step}` : ''}`;
        if (missing) response = queued && queued.trim() !== 'nobody'
          ? `Telegram queued for ${displayNames(queued)}; no Telegram chat for ${displayNames(missing)}`
          : `No Telegram chat for ${displayNames(missing)} — alert on screen only`;
        else if (/telegram off/i.test(raw)) response += ' (screen only)';
        else if (names && /telegram queued/i.test(raw)) response = `${names} paged (Telegram queued)`;
        if (missing || /telegram off/i.test(raw) || !/telegram queued/i.test(raw))
          what = response.replace(/^./, c => c.toUpperCase());
        sentence = `${wait ? `No one acknowledged in ${wait} s — ` : ''}${response}`;
      } else if (/^IT notified:/i.test(raw)) {
        const channel = /screen only|telegram off/i.test(raw) ? ' (Security screen only)'
          : /telegram IT group queued/i.test(raw) ? ' (Telegram queued)' : '';
        sentence = `IT alert for ${monitor}${channel}`;
        if (/screen only|telegram off/i.test(raw)) what = `IT alert for ${monitor} (Security screen only)`;
      }
      why = /no acknowledgement/i.test(raw) ? 'Nobody has acknowledged yet' : securityReason || (/EMERGENCY/i.test(raw) ? 'Possible patient emergency' : /LOOSE_SENSOR/i.test(raw) ? 'Sensor needs refitting' : 'Bed needs a check');
      break;
    }
    case 'edit_message': {
      const completed = /IT message updated:\s*Device cut off \d/i.test(raw);
      if (/IT message/i.test(raw)) {
        const channel = /screen only|telegram off/i.test(raw) ? ' (Security screen only)'
          : /telegram IT group queued/i.test(raw) ? ' (Telegram queued)' : '';
        const state = /DRY RUN/i.test(raw) ? 'cut-off simulated'
          : /\bFAILED\b/.test(raw) ? 'cut-off failed'
          : /Device not cut off/i.test(raw) ? 'not cut off'
          : /device still connected/i.test(raw) ? 'still connected'
          : /Cutting off device/i.test(raw) ? 'cut-off pending'
          : completed ? 'cut off' : 'alert updated';
        sentence = `IT update: ${monitor} ${state}${/untrusted/i.test(raw) ? ' — data untrusted' : ''}${channel}`;
      }
      what = /IT/i.test(raw) ? 'Updated IT security' : 'Updated the bedside alert';
      why = completed ? 'Monitor has been cut off' : /untrusted/i.test(raw) ? 'Readings are not trusted' : 'Alert status changed';
      break;
    }
    case 'disable_client':
      what = /^DRY RUN:/i.test(raw) ? `Simulated cut-off of ${monitor}`
        : /\bFAILED\b/.test(raw) ? `Could not cut off ${monitor}` : `Cut off ${monitor} at the hub`;
      why = /^DRY RUN:/i.test(raw) ? 'Simulation only; no hub change' : /\bFAILED\b/.test(raw) ? 'Hub cut-off failed; IT review needed' : securityReason || why;
      break;
    case 'isolate_device':
      what = `Requested cut-off of ${monitor}`; why = 'Awaiting confirmation from the hub'; break;
    case 'set_bed_untrusted':
      what = 'Marked readings as not trusted'; why = securityReason || 'Signals need a bedside check'; break;
    case 'capture_evidence':
      what = 'Captured a bedside snapshot'; why = 'Keep a record of the current bed state'; break;
    case 'snapshot_files': {
      const minutes = raw.match(/(?:last\s+)?(\d+)\s*min/i)?.[1];
      what = minutes ? `Sealed ${minutes} min of evidence` : 'Sealed the incident evidence';
      why = 'Keep a record of the suspected attack'; break;
    }
    case 'hash_file': {
      const record = /messages|readings/i.test(raw) ? 'signal record' : /verdicts/i.test(raw) ? 'decision record' : /timeline/i.test(raw) ? 'event timeline' : /network/i.test(raw) ? 'network record' : 'evidence file';
      what = `Fingerprinted the ${record}`; why = 'Make later changes detectable'; break;
    }
    case 'write_timeline':
      what = 'Started the incident timeline'; why = 'Preserve the order of events'; break;
    case 'draft_report':
      what = 'Drafted the CERT-In report';
      why = raw.match(/(\d+) fields? need/) ? `${raw.match(/(\d+) fields? need/)![1]} fields need a person` : 'Ready for a person to review'; break;
    case 'start_clock':
      what = 'Started the 6-hour report clock'; why = 'Track the incident reporting deadline'; break;
    case 'list_devices': {
      const count = raw.match(/(\d+) devices/i)?.[1];
      what = count ? `Checked ${count} monitors across the ward` : 'Checked monitors across the ward';
      const source = raw.match(/after (MON-\d+) was cut off/i)?.[1];
      const findings = raw.split(/Check next:\s*/i)[1];
      const followUp = findings?.match(/MON-\d+/g);
      const outcome = findings && /^none flagged\b/i.test(findings) ? ': none flagged'
        : followUp?.length ? `: follow-up needed on ${[...new Set(followUp)].join(', ')}` : '';
      sentence = `Checked ${count ? `${count} ` : ''}${source ? 'other ' : ''}monitors${source ? ` after ${source} cut-off` : ' across the ward'}${outcome}`;
      if (/no other devices/i.test(raw)) sentence = 'No other monitors of this model in the inventory';
      why = 'Look for the same attack elsewhere'; break;
    }
    case 'set_watch_level': {
      const count = raw.match(/for\s+(\d+)/i)?.[1];
      what = count ? `Raised watch on ${count} monitors` : 'Raised the fleet watch level';
      const model = raw.match(/'([^']+)'/i)?.[1];
      const group = `${count ? `${count} ` : ''}${model === 'demo-monitor' ? 'demo monitors' : 'monitors'}`;
      const until = raw.match(/until (\d{1,2}:\d{2})/i)?.[1];
      const ended = /back to normal/i.test(raw);
      if (ended) { what = 'Restored normal watch'; why = /expired/i.test(raw) ? 'Extra watch period ended' : 'Earlier watch reversed'; }
      else why = 'Look for related attacks';
      sentence = ended ? `Extra watch ended for ${group}` : `Extra watch on ${group}${until ? ` until ${until}` : ''}`;
      break;
    }
    case 'write_briefing':
      sentence = `Shift briefing updated${/template/i.test(raw) ? /still writing|busy with/i.test(raw) ? ' (template; Granite busy)' : /reject/i.test(raw) ? ' (template; Granite draft failed fact check)' : /unavailable|SW_GRANITE_URL not set/i.test(raw) ? ' (template; Granite unavailable)' : ' (template)' : /granite/i.test(raw) ? ' (IBM Granite)' : ''}`;
      what = 'Updated the handover briefing';
      why = /rejected/i.test(raw) ? 'Granite draft failed the fact check' : /still writing/i.test(raw) ? 'Template used while Granite writes' : /template/i.test(raw) ? 'Template used from ward facts' : 'Summarise the shift for handover'; break;
    case 'silence_alarm': case 'suppress_alarm':
      what = 'Flagged a sensor episode (advice only)'; why = 'Refit the sensor; alarms remain active'; break;
    case 'open_ticket': case 'create_ticket':
      what = 'Opened a repair ticket'; why = /DRIFT|drift/i.test(raw) ? 'Pressure sensor drifting' : /LOOSE|loose/i.test(raw) ? 'Sensor keeps coming loose' : 'Monitor needs a repair'; break;
    case 'update_ticket':
      what = /resolved|done/i.test(raw) ? 'Resolved the repair ticket' : 'Updated the repair ticket'; why = 'Repair status recorded'; break;
    case 'acknowledge_alert': case 'ack_alert':
      what = 'Acknowledged the alert'; why = 'A staff member is responding'; break;
    case 'record_ack': {
      const withdrawn = /withdrawn/i.test(raw);
      const person = raw.match(/acknowledged by\s+(\S+)\s+via/i)?.[1];
      what = withdrawn ? 'Withdrew the acknowledgement' : 'Acknowledged the alert';
      why = withdrawn ? 'Alert re-opened; escalation restarted' : 'A staff member is responding';
      sentence = withdrawn ? 'Acknowledgement withdrawn — alert open again'
        : `Alert acknowledged${person ? ` by ${actorName(person)}` : ''}`;
      break;
    }
    case 'confirm_bedside': case 'bedside_check':
      what = /patient_not_ok/i.test(raw) ? 'Recorded a bedside concern' : /patient_ok/i.test(raw) ? 'Confirmed the patient is OK' : 'Recorded a bedside check'; why = 'Patient checked in person'; break;
    case 'enable_client':
      what = /^DRY RUN:/i.test(raw) ? `Simulated reconnection of ${monitor}`
        : /\bFAILED\b/.test(raw) ? `Could not reconnect ${monitor}`
        : /had not been cut off/i.test(raw) ? 'Restored trusted readings — no hub reconnection needed'
        : /no second hub change/i.test(raw) ? 'Recorded the earlier reconnection' : `Reconnected ${monitor} at the hub`;
      why = /^DRY RUN:/i.test(raw) ? 'Simulation only; no hub change'
        : /\bFAILED\b/.test(raw) ? 'Monitor remains cut off; IT must retry'
        : /had not been cut off/i.test(raw) ? 'Monitor was already connected'
        : /demo reset/i.test(raw) ? 'Demo reset restored the connection' : /no second hub change/i.test(raw) ? 'Same release · no extra hub change' : 'Reverses the earlier cut-off';
      break;
    case 'reenable_client': case 'undo_disable_client': case 'undo_action':
      what = /watch/i.test(raw) ? 'Restored the previous watch level' : `Requested reconnection of ${monitor}`; why = 'Reverses an earlier action'; break;
    case 'write_workload': case 'workload_check': case 'check_workload':
      what = 'Reviewed the nurses’ alarm load'; why = 'Check whether beds need rebalancing'; break;
    case 'warn_workload': {
      const counts = raw.match(/(\S+) received (\d+) alarms in the last (\d+) h/i);
      const withdrawn = raw.match(/Workload warning for (\S+) withdrawn/i);
      what = withdrawn ? 'Withdrew the workload warning' : 'Flagged a high alarm load';
      why = withdrawn ? 'A person withdrew the warning' : 'Charge nurse decides whether to share the alarm load';
      sentence = withdrawn ? `Workload warning for ${actorName(withdrawn[1])} withdrawn`
        : counts ? `${actorName(counts[1])} received ${counts[2]} alarms in ${counts[3]} h — charge nurse review needed` : what;
      break;
    }
    case 'recommend_rebalance': case 'rebalance_beds':
      what = 'Suggested a more even bed assignment'; why = 'Alarm load is uneven'; break;
    case 'close_alert': case 'auto_close_alert':
      what = 'Closed the alert automatically'; why = 'Bed state changed'; break;
    case 'open_incident':
      what = 'Opened a security incident'; why = securityReason || 'Investigate suspicious signals'; break;
    case 'contain_incident':
      what = 'Requested incident containment'; why = 'Keep the monitor cut off'; break;
    case 'resolve_incident':
      what = 'Closed the security incident'; why = 'IT recorded the resolution'; break;
    case 'review_report': case 'edit_report':
      what = 'Reviewed the CERT-In draft'; why = 'Prepare the report for human approval'; break;
    case 'mark_report_sent':
      what = 'Recorded the report as sent'; why = 'A person confirmed sending it'; break;
    case 'demo_run': case 'run_demo':
      what = 'Started a demo scenario'; why = 'Operator requested a simulated ward run'; break;
    case 'demo_reset': case 'reset_demo':
      what = 'Reset the demo ward'; why = 'Operator requested a fresh run'; break;
  }
  const summary = `${a.bed_id ? `${a.bed_id} · ` : ''}${sentence ?? (what === 'Recorded an action' ? 'Action recorded — see Details' : what)}`;
  return {who, kind, what, bed: a.bed_id || 'Ward', why, summary};
}

/** Plain language for prose fields; audit identifiers remain in the original record disclosure. */
export function plainText(value: string): string {
  return value
    .replace(/\b(?:al|rp|rep|inc|br|cmd|act|tk|ticket)_[a-z0-9_-]+\b/gi, 'the record')
    .replace(/\bstaff:([a-z_]+)/gi, (_, n: string) => actorName(n))
    .replace(/\bDr_mehta\b/g, 'Dr Mehta')
    .replace(/verdict\.last_trusted_ts/g, 'last trusted signal time')
    .replace(/\bpatient_not_ok\b/g, 'patient needs attention').replace(/\bpatient_ok\b/g, 'patient OK')
    .replace(/\bBOTH\b/g, 'emergency on a hacked monitor')
    .replace(/\b(?:TAMPERING|DEVICE_ATTACK)\b/g, 'monitor hacked')
    .replace(/\bUNSURE\b/g, 'check by hand').replace(/\bUNTRUSTED\b/g, 'not trusted')
    .replace(/\bDRIFTING\b/g, 'sensor drift').replace(/\bLOOSE_SENSOR\b/g, 'loose sensor')
    .replace(/\bNORMAL\b/g, 'normal').replace(/\bEMERGENCY\b/g, 'emergency')
    .replace(/\s*\(conf\s+[\d.]+\)/g, '')
    .replace(/\bA[1-8]\b/g, a => AGENTS[a])
    .replace(/;?\s*telegram[^;.]*/gi, '');
}
