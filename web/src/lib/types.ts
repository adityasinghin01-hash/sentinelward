export type Role='nurse'|'doctor'|'it'|'biomedical'|'operator';
export interface Session {token:string;role:Role;name:string;display_name:string}
export type Verdict='NORMAL'|'EMERGENCY'|'BOTH'|'TAMPERING'|'UNSURE'|'DRIFTING'|'LOOSE_SENSOR'|'DEVICE_ATTACK';
export type Priority='none'|'high'|'medium'|'low';
export interface Vitals {hr:number|null;spo2:number|null;systolic:number|null;diastolic:number|null}
export interface Wave {ecg:number[];ppg:number[]}
export interface Bed {bed_id:string;device_id:string;patient?:{initials:string;age:number|null;sex:string|null};verdict:Verdict|null;priority:Priority;trust_score:number;is_trusted:boolean;connected:boolean;isolated:boolean;reason:string;requested_action:string;acknowledged:boolean;last_updated_at:number|null;vitals:Vitals|null;waveform:Wave;last_trusted:{captured_at:number;vitals:Vitals;waveform:Wave}|null;display:'live'|'last_trusted'|'offline'|'empty';offline_since:number|null;manual:Record<string,unknown>|null;last_bedside_check:Record<string,unknown>|null;assignment:Record<string,unknown>|null;nurse_call:Record<string,unknown>|null}
export interface Score {score:number|null;reason:string;label:string;model_version?:string;window_start?:number;extra:Record<string,unknown>}
export interface VerdictMsg {ts:number;verdict:Verdict;priority:Priority;confidence:number|null;trust:number|null;reasons:string[];scores:Record<string,number|null>;last_trusted_ts:number|null}
export interface BedDetail extends Bed {scores:Record<string,Score>;recent_verdicts:VerdictMsg[];open_alerts:Alert[];device:{online:boolean;isolated:boolean;isolated_since:number|null;last_seen_ts:number|null}}
export interface NetFeatures {device_id:string;window_start:number;window_s:number;msgs_per_s:number|null;bytes_per_s:number|null;iat_mean_ms:number|null;iat_std_ms:number|null;payload_mean:number|null;payload_std:number|null;senders:number|null;connects_per_s:number|null;malformed:number|null;seq_gaps:number|null;seq_repeats:number|null;stale_ms:number|null}
export interface ReportField {value:string|number|boolean|null;status:'observed'|'profile'|'attested'|'missing';source:string}
export interface Alert {alert_id:string;ts:number;bed_id:string;verdict:Verdict;priority:Priority;text:string;to:string[];ladder_step:number;status:string;acked_by:string|null;acked_ts:number|null}
export interface Action {id:string;occurred_at:number;actor:string;action_code:string;action:string;bed_id:string|null;device_id:string|null;approved_by:string|null;mode:'automatic'|'person';undoable:boolean;references_action_id:string|null}
export interface Device {device_id:string;bed_id:string;online:boolean;isolated:boolean;isolated_since:number|null;last_seen_ts:number|null;net:NetFeatures|null}
export interface AgentRecord {record_id:string;kind:string;ts:number;by:string;version:number;data:Record<string,unknown>;updated_ts:number|null;updated_by:string|null}
export interface HistoryPoint {ts:number;hr:number|null;spo2:number|null;sys:number|null;dia:number|null;rr:number|null;map?:number|null;abp_mean?:number|null;trusted:boolean;verdict:string|null}
export interface Briefing {since:string;generated_by:string;summary:string;incidents:number;untrusted_beds:number;open_tickets:number;blind_time:{bed_id:string;minutes:number}[];ts:number}
export interface Workload {nurses:{nurse_id:string;nurse_name:string;alarms_last_2h:number}[]}
export interface Receipt {command_id:string;accepted_at:number;request_id?:string}
