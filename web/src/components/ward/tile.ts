import type {Alert, Bed, Verdict} from '../../lib/types';
import {age, bedState, displayVitals, isOpenAlert} from '../../lib/domain';

export type TileKey = Verdict | 'NO_SIGNAL' | 'ALARM_OPEN';
export type TileGroup = 'emergency' | 'security' | 'check' | 'nosignal' | 'maint' | 'normal';

export interface TileView {
  key: TileKey;
  group: TileGroup;
  tone: 'emergency' | 'both' | 'security' | 'check' | 'maint' | 'nodata' | 'ok';
  word: string;
  reason: string;
  untrusted: boolean;
  offline: boolean;
  footer: string | null;
  alert: Alert | null;
}

const GROUP_ORDER: Record<TileGroup, number> = {emergency: 0, security: 1, check: 2, nosignal: 3, maint: 4, normal: 5};
const PRIORITY: Record<string, number> = {high: 0, medium: 1, low: 2, none: 3};

/** The bed's most urgent open alert, if any. */
export function openAlertFor(bedId: string, alerts: Alert[]): Alert | null {
  const open = alerts.filter(a => a.bed_id === bedId && isOpenAlert(a));
  open.sort((a, b) => (PRIORITY[a.priority] ?? 3) - (PRIORITY[b.priority] ?? 3) || b.ts - a.ts);
  return open[0] ?? null;
}

/** What one tile must say: the WORSE of the verdict and the bed's open alert (a bed with an open emergency alert never looks normal). */
export function tileView(bed: Bed, alerts: Alert[], now: number): TileView {
  const s = bedState(bed, now);
  const alert = openAlertFor(bed.bed_id, alerts);
  const lastGood = bed.last_trusted?.captured_at;
  const footerUntrusted = lastGood ? `Not trusted · last good ${age(lastGood, now)} ago` : 'Not trusted · no good reading yet';
  const v = bed.verdict === 'EMERGENCY' && bed.isolated ? 'BOTH' : bed.verdict;
  const base = (key: TileKey, group: TileGroup, tone: TileView['tone'], word: string, reason: string, footer: string | null = null): TileView =>
    ({key, group, tone, word, reason, untrusted: s.untrusted, offline: s.offline, footer, alert});

  let view: TileView;
  if (v === 'BOTH') view = base('BOTH', 'emergency', 'both', 'Emergency · attack suspected', 'Go now · check by hand', bed.isolated ? 'Data untrusted · device flagged' : footerUntrusted);
  else if (v === 'EMERGENCY') view = base('EMERGENCY', 'emergency', 'emergency', 'Emergency', 'Go now · monitor alarm');
  else if (v === 'TAMPERING' || v === 'DEVICE_ATTACK') view = base(v, 'security', 'security', v === 'TAMPERING' ? 'Possible tampering' : 'Device attack suspected', bed.isolated ? 'Data untrusted · device flagged' : 'Numbers not trusted · IT alerted', bed.isolated ? 'Data untrusted · device flagged' : footerUntrusted);
  else if (bed.isolated) view = base('TAMPERING', 'security', 'security', 'Data untrusted · device flagged', 'Check by hand · IT review needed', 'Nothing it sends is trusted');
  else if (s.offline && v !== 'UNSURE') view = base('NO_SIGNAL', 'nosignal', 'nodata', bed.last_updated_at ? `No signal · ${age(bed.last_updated_at, now)}` : 'No signal', bed.last_updated_at ? 'Monitor silent · check by hand' : 'Awaiting first signal');
  else if (v === 'UNSURE') view = base('UNSURE', 'check', 'check', 'Check by hand', 'Readings unclear', s.untrusted ? footerUntrusted : null);
  else if (v === 'DRIFTING') view = base('DRIFTING', 'maint', 'maint', 'Sensor drift', 'Pressure line drifting · re-zero');
  else if (v === 'LOOSE_SENSOR') view = base('LOOSE_SENSOR', 'maint', 'maint', 'Loose sensor', 'Refit sensor · false alarm');
  else view = base('NORMAL', 'normal', 'ok', 'Normal', '', s.untrusted ? footerUntrusted : null);

  // Worse-of with the open alert.
  if (alert && alert.priority === 'high' && view.group !== 'emergency')
    view = {...view, key: 'ALARM_OPEN', group: 'emergency', tone: 'emergency', word: `Alarm open · step ${alert.ladder_step}/3`, reason: 'Go now · see alert'};
  else if (alert && alert.priority === 'medium' && (view.group === 'normal' || view.group === 'maint' || view.group === 'nosignal'))
    view = {...view, group: 'check', tone: 'check', word: `Alert open · step ${alert.ladder_step}/3`, reason: 'Check by hand · see alert'};
  return view;
}

export interface VitalFlags {hr: 'high' | 'low' | null; spo2: 'low' | null; sys: 'high' | 'low' | null}
/** Display-only flags (not alarms): outside common alert limits. */
export function vitalFlags(bed: Bed): VitalFlags {
  const v = displayVitals(bed);
  const n = (x: number | null | undefined) => typeof x === 'number' && Number.isFinite(x);
  return {
    hr: n(v?.hr) ? (v!.hr! > 120 ? 'high' : v!.hr! < 50 ? 'low' : null) : null,
    spo2: n(v?.spo2) && v!.spo2! < 90 ? 'low' : null,
    sys: n(v?.systolic) ? (v!.systolic! > 180 ? 'high' : v!.systolic! < 90 ? 'low' : null) : null,
  };
}

/** Problem beds first; stable (bed order) inside a group, so tiles only move when their group changes. */
export function orderBeds(beds: Bed[], views: Map<string, TileView>): Bed[] {
  return [...beds].sort((a, b) => GROUP_ORDER[views.get(a.bed_id)!.group] - GROUP_ORDER[views.get(b.bed_id)!.group] || a.bed_id.localeCompare(b.bed_id));
}

/** Plain one-line text for an alert in the rail. */
export function alertLine(a: Alert): string {
  switch (a.verdict) {
    case 'BOTH': return 'Go now · do not trust the numbers';
    case 'EMERGENCY': return 'Possible emergency · go now';
    case 'TAMPERING': case 'DEVICE_ATTACK': return 'Possible tampering · check by hand';
    case 'UNSURE': return 'Readings unclear · check by hand';
    case 'DRIFTING': return 'Pressure sensor drifting';
    case 'LOOSE_SENSOR': return 'Sensor loose · refit it';
    default: return 'Check this bed';
  }
}
