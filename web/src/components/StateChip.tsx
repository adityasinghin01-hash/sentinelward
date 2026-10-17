import {Activity, AlertTriangle, Circle, ShieldAlert, Unplug, Wrench} from 'lucide-react';
import type {Verdict} from '../lib/types';

export const stateChips = {
  NORMAL: {word:'NORMAL',tone:'ok',icon:Circle},
  EMERGENCY: {word:'EMERGENCY',tone:'emergency',icon:AlertTriangle},
  BOTH: {word:'EMERGENCY · ATTACK SUSPECTED',tone:'both',icon:ShieldAlert},
  TAMPERING: {word:'POSSIBLE TAMPERING',tone:'security',icon:ShieldAlert},
  DEVICE_ATTACK: {word:'DEVICE ATTACK SUSPECTED',tone:'security',icon:ShieldAlert},
  UNSURE: {word:'CHECK BY HAND',tone:'check',icon:AlertTriangle},
  DRIFTING: {word:'SENSOR DRIFT',tone:'maint',icon:Activity},
  LOOSE_SENSOR: {word:'LOOSE SENSOR',tone:'maint',icon:Wrench},
  NO_DATA: {word:'NO DATA',tone:'nodata',icon:Unplug},
} as const;
export function StateChip({state,className=''}:{state:Verdict|'NO_DATA'|null;className?:string}) {
  const {word,tone,icon:Icon}=stateChips[state??'NO_DATA'];
  return <span className={`state-chip state-${tone} ${className}`} data-state={state??'NO_DATA'}><Icon size={14} aria-hidden="true"/>{word}</span>;
}
