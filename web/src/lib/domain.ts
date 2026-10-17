import type {Bed,Alert,Role,Priority} from './types';
export const modelChecks:Record<string,{label:string;meaning:string}>={M1:{label:'Sensor unusable',meaning:'How likely the sensor signal is unusable.'},M2:{label:'Real emergency',meaning:'How likely the alarm reflects a real patient emergency.'},M3:{label:'Body mismatch',meaning:'How likely heart and pulse signals disagree.'},M4:{label:'Replay',meaning:'How likely a previous signal is being replayed.'},M5:{label:'Network attack',meaning:'How likely the network traffic indicates an attack.'},M6:{label:'Pressure drift',meaning:'How likely the pressure signal has drifted from its reference.'}};
const labels={NORMAL:'Normal',EMERGENCY:'EMERGENCY',BOTH:'EMERGENCY + UNTRUSTED',TAMPERING:'UNTRUSTED',UNSURE:'UNSURE',DRIFTING:'DRIFTING SENSOR',LOOSE_SENSOR:'LOOSE SENSOR',DEVICE_ATTACK:'IT investigating'};
export function bedState(b:Bed,now=Date.now()){const offline=!b.connected||b.display==='offline'||b.last_updated_at===null||now-b.last_updated_at>5000;const untrusted=!b.is_trusted||b.display==='last_trusted'||b.verdict==='BOTH'||b.verdict==='TAMPERING';const tone:Priority=b.verdict==='DEVICE_ATTACK'?'none':b.verdict==='TAMPERING'?'none':b.priority;return {offline,untrusted,tone,label:b.verdict?labels[b.verdict]||'UNSURE':b.display==='empty'?'NO MONITOR':'AWAITING VERDICT'};}
export function displayVitals(b:Bed){return !b.is_trusted&&b.last_trusted?b.last_trusted.vitals:b.vitals;}
export function mergeBed(beds:Bed[],next:Bed){return beds.some(b=>b.bed_id===next.bed_id)?beds.map(b=>b.bed_id===next.bed_id?next:b):[...beds,next].sort((a,b)=>a.bed_id.localeCompare(b.bed_id));}
export function dedupeAlerts(alerts:Alert[]){const map=new Map<string,Alert>();for(const a of alerts){if(!map.has(a.alert_id)||map.get(a.alert_id)!.ts<a.ts)map.set(a.alert_id,a);}return [...map.values()].sort((a,b)=>b.ts-a.ts);}
export const roleHomes:Record<Role,string>={nurse:'/ward',doctor:'/census',it:'/security',biomedical:'/tickets',operator:'/demo'};
export const roleNames:Record<Role,string>={nurse:'Central nurse',doctor:'Doctor / tele-ICU',it:'IT security',biomedical:'Biomedical engineer',operator:'Demo operator'};
const allowed:Record<Role,string[]>={nurse:['ward','bed','alerts','briefing','log'],doctor:['ward','bed','census','alerts','briefing','log'],it:['ward','bed','security','incident','log'],biomedical:['tickets','log'],operator:['ward','bed','alerts','census','security','incident','tickets','briefing','log','demo']};
export function canOpen(role:Role,page:string){return allowed[role].includes(page);}
// Write permissions exactly as the backend enforces them (backend/sw_api: roles(...)).
const writers:Record<string,Role[]>={clinical:['nurse','doctor'],security:['it','operator'],report:['it','operator'],ticketEdit:['biomedical','operator'],demo:['operator']};
export function can(role:Role|undefined,what:keyof typeof writers|string){return !!role&&(writers[what]||[]).includes(role);}
export const verdictWords:Record<string,string>={NORMAL:'Normal',EMERGENCY:'Real emergency',BOTH:'Emergency on an untrusted monitor',TAMPERING:'Data untrusted (possible tampering)',UNSURE:'Unsure: check by hand',DRIFTING:'Pressure sensor drifting',LOOSE_SENSOR:'Loose sensor',DEVICE_ATTACK:'Device under attack (IT)'};
export function ticketColumn(status:unknown):'new'|'progress'|'done'{const s=String(status||'new');return ['resolved','done','closed'].includes(s)?'done':['assigned','in_progress','progress'].includes(s)?'progress':'new';}
export const certFields:{group:string;fields:[string,string][]}[]=[
 {group:'Reporter and organisation',fields:[['reporter_name','Reporter name'],['reporter_role','Reporter role'],['organisation','Organisation'],['phone','Phone'],['mobile','Mobile'],['email','Email'],['address','Address']]},
 {group:'Affected system',fields:[['affected_entity','Affected entity'],['sector','Sector'],['critical_to_mission','Critical to mission'],['ip_address','IP address'],['hostname','Host name'],['os_version','OS / firmware version'],['last_patched','Last patched'],['vendor','Vendor'],['model','Model'],['location','Location']]},
 {group:'Incident',fields:[['incident_type','Type of incident'],['symptoms','Symptoms observed'],['actions_taken','Actions taken'],['evidence_summary','Evidence summary']]},
];
export const longFields=new Set(['address','symptoms','actions_taken','evidence_summary']);
export function dateTime(ts:number|null|undefined){return ts?new Date(ts).toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'Not recorded';}
export function staff(id:unknown){return typeof id==='string'?id.replace(/^staff:/,'').replace(/^./,c=>c.toUpperCase()):'—';}
export function bytes(n:unknown){return typeof n==='number'?n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KB`:`${(n/1048576).toFixed(1)} MB`:'—';}
export function score01(n:unknown){return typeof n==='number'&&Number.isFinite(n)?n.toFixed(2):'—';}
export function downloadName(...parts:string[]){return parts.join('_').replace(/[^\w.-]+/g,'_').replace(/(\.json)?$/,'.json');}
export function reportReady(r:Record<string,unknown>){return r.factsChecked===true&&r.evidenceAttached===true&&typeof r.approver==='string'&&r.approver.trim().length>0;}
export const time=(ts:number|null|undefined,seconds=false)=>ts?new Date(ts).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',...(seconds?{second:'2-digit'}:{})}):'Not recorded';
export function age(ts:number|null|undefined,now=Date.now()){if(!ts)return 'not received';const s=Math.max(0,Math.floor((now-ts)/1000));return s<60?`${s} s`:`${Math.floor(s/60)} min`;}
export const value=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)?Math.round(n).toString():'—';
export function text(v:unknown,fallback='Not recorded'):string{return typeof v==='string'?v:Array.isArray(v)?v.map(x=>typeof x==='object'?JSON.stringify(x):String(x)).join('\n'):typeof v==='number'?String(v):fallback;}
export function deadline(r:Record<string,unknown>,ts:number){const n=r.report_deadline_ts??r.deadline_ts??r.report_due_at??r.deadline??r.cert_in_deadline;return typeof n==='number'?n:typeof n==='string'&&!isNaN(Date.parse(n))?Date.parse(n):ts+6*3600000;}
export function countdown(due:number,now=Date.now()){const sec=Math.max(0,Math.floor((due-now)/1000));return `${Math.floor(sec/3600)}:${String(Math.floor(sec%3600/60)).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`;}
