import type {Bed,BedDetail,Alert,Role,Priority,AgentRecord} from './types';
export const modelChecks:Record<string,{label:string;meaning:string}>={M1:{label:'Sensor unusable',meaning:'How likely the sensor signal is unusable.'},M2:{label:'Real emergency',meaning:'How likely the alarm reflects a real patient emergency.'},M3:{label:'Body mismatch',meaning:'How likely heart and pulse signals disagree.'},M4:{label:'Replay',meaning:'How likely a previous signal is being replayed.'},M5:{label:'Network attack',meaning:'How likely the network traffic indicates an attack.'},M6:{label:'Pressure drift',meaning:'How likely the pressure signal has drifted from its reference.'}};
const labels={NORMAL:'Normal',EMERGENCY:'EMERGENCY',BOTH:'EMERGENCY · ATTACKED MONITOR',TAMPERING:'UNTRUSTED',UNSURE:'UNSURE',DRIFTING:'DRIFTING SENSOR',LOOSE_SENSOR:'LOOSE SENSOR',DEVICE_ATTACK:'IT investigating'};
export function bedState(b:Bed,now=Date.now()){const offline=!b.connected||b.display==='offline'||b.last_updated_at===null||now-b.last_updated_at>5000;const untrusted=!b.is_trusted||b.display==='last_trusted'||b.verdict==='BOTH'||b.verdict==='TAMPERING';const tone:Priority=b.verdict==='DEVICE_ATTACK'?'none':b.verdict==='TAMPERING'?'none':b.priority;return {offline,untrusted,tone,label:b.verdict==='EMERGENCY'&&b.isolated?labels.BOTH:b.verdict?labels[b.verdict]||'UNSURE':b.display==='empty'?'NO MONITOR':'AWAITING VERDICT'};}
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
export const verdictWords:Record<string,string>={NORMAL:'Normal',EMERGENCY:'Emergency (monitor alarm)',BOTH:'Emergency alarm on an attacked monitor',TAMPERING:'Data untrusted (possible tampering)',UNSURE:'Unsure: check by hand',DRIFTING:'Pressure sensor drifting',LOOSE_SENSOR:'Loose sensor',DEVICE_ATTACK:'Device under attack (IT)'};
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

// ---- One definition for each number the screens share ----

/** Alerts still waiting for a person: not acknowledged and not closed. Ward stat, alert rail, strip and Alerts tab all use this. */
export const isOpenAlert=(a:Alert)=>a.status==='open'||a.status==='escalated';
export const openAlerts=(alerts:Alert[])=>alerts.filter(isOpenAlert);
/** Acknowledged = a person took it (acked_by set). Alerts the agents closed on their own are not acknowledged. */
export const isAckedAlert=(a:Alert)=>!!a.acked_by||a.status==='acked';
export const isAutoClosedAlert=(a:Alert)=>!isOpenAlert(a)&&!isAckedAlert(a);

/** Data trust as shown: a cut-off, offline or never-checked monitor is "not trusted", whatever number it last carried. */
export function trustView(b:Pick<Bed,'isolated'|'connected'|'display'|'verdict'|'trust_score'>):{value:number|null;text:string;why:string}{
 if(b.isolated)return {value:null,text:'not trusted',why:'Monitor cut off by IT: nothing it sends is trusted, whatever score it last carried.'};
 if(!b.connected||b.display==='offline')return {value:null,text:'not trusted',why:'Monitor offline: no live data to trust. The screen keeps the last trusted values.'};
 if(b.display==='empty'||b.verdict===null)return {value:null,text:'—',why:'No verdict yet, so there is no trust score.'};
 const v=Math.max(0,Math.min(1,(b.trust_score||0)/100));return {value:v,text:v.toFixed(2),why:''};
}
/** Trust attached to one past verdict: not shown for verdicts made after the monitor was cut off or went silent. */
export function verdictTrust(trust:number|null|undefined,ts:number,b:Pick<Bed,'isolated'|'connected'|'display'|'offline_since'>&{device?:{isolated_since:number|null}}){
 const since=b.isolated?(b.device?.isolated_since??0):(!b.connected||b.display==='offline')?(b.offline_since??0):null;
 return since!==null&&ts>=since?'not trusted':score01(trust);
}

/** The words a bed's verdict is shown with: headline, the action, and the AI check line (never "confidence 1.00" for alarms). */
export interface VerdictView {headline:string;alarm:string|null;aiCheck:string|null;why:string|null;showConfidence:boolean}
export function verdictView(d:Pick<BedDetail,'verdict'|'reason'|'isolated'|'connected'|'display'>&Partial<Pick<BedDetail,'scores'|'monitor_alarm'|'recent_verdicts'>>):VerdictView{
 const reasons=d.recent_verdicts?.[0]?.reasons?.length?d.recent_verdicts[0].reasons:d.reason?[d.reason]:[];
 const m2=d.scores?.M2;const x=(m2?.extra??{}) as Record<string,unknown>;
 const code=typeof x.alarm_code==='string'?x.alarm_code:typeof d.monitor_alarm?.code==='string'?d.monitor_alarm.code:null;
 const score=typeof m2?.score==='number'?m2.score:null;const thr=typeof x.threshold==='number'?x.threshold:null;
 const aiCheck=score===null?`AI check: not available${m2?.reason?` (${m2.reason})`:''}`:thr===null?`AI check: score ${score.toFixed(2)} (no threshold reported)`:`AI check: ${score>=thr?'likely real':'likely false'} (score ${score.toFixed(2)}, threshold ${thr.toFixed(2)})`;
 const alarm=`Monitor alarm: ${code??'code not reported'}`;
 if(d.verdict==='BOTH'||(d.verdict==='EMERGENCY'&&d.isolated))return {headline:'Emergency alarm on an attacked monitor — go now, check by hand; numbers not trusted',alarm,aiCheck,why:null,showConfidence:false};
 if(d.verdict==='EMERGENCY'){const down=!d.connected||d.display==='offline';return {headline:down?'Emergency alarm on an offline monitor — go now, check by hand':'Emergency: monitor alarm — go now',alarm,aiCheck,why:null,showConfidence:false};}
 if(d.verdict==='UNSURE')return {headline:'Unsure: check by hand',alarm:null,aiCheck:null,why:reasons[0]?`Blocked by: ${reasons[0]}`:'Blocked by: no reason reported',showConfidence:false};
 return {headline:d.verdict?verdictWords[d.verdict]??d.verdict:d.reason||'Awaiting first verdict',alarm:null,aiCheck:null,why:null,showConfidence:!!d.verdict&&d.connected&&!d.isolated&&d.display!=='offline'};
}

/** CERT-In 6-hour clock, one anchor for every screen: the report's own deadline, else 6 h from when the incident was noticed. */
export function certDeadline(report:AgentRecord|null|undefined,incident:AgentRecord|null|undefined):number|null{
 const r=report?.data??{},i=incident?.data??{};const n=(v:unknown)=>typeof v==='number'&&v>0?v:null;
 const direct=n(r.clock_deadline_ts)??n(r.deadline_ts);if(direct)return direct;
 const start=n(r.clock_started_ts)??n(r.noticed_ts)??n(i.detected_ts)??n(i.opened_ts)??(incident?incident.ts:null)??(report?report.ts:null);
 return start?start+6*3600_000:null;
}

/** CERT-In form value from an A5 draft: a saved field first, else the agent's flat draft keys. */
const reportPaths:Record<string,string[]>={reporter_name:['reporter_name'],reporter_role:['reporter_role'],organisation:['organisation'],phone:['reporter_phone','phone'],mobile:['reporter_mobile','mobile'],email:['reporter_email','email'],address:['address','organisation_address'],affected_entity:['affected_entity','affected_system.device_id','device_id'],sector:['sector'],critical_to_mission:['critical_to_mission'],ip_address:['affected_system.ip_address','ip_address'],hostname:['affected_system.host_name','hostname'],os_version:['affected_system.os_version','os_version'],last_patched:['affected_system.last_patched','last_patched'],vendor:['affected_system.vendor','vendor'],model:['affected_system.hardware_model','model'],location:['physical_location','location'],incident_type:['incident_type'],symptoms:['symptoms'],actions_taken:['actions_taken'],evidence_summary:['evidence_summary','evidence']};
export function reportValue(data:Record<string,unknown>,key:string):string{
 for(const path of reportPaths[key]??[key]){let v:unknown=data;for(const part of path.split('.'))v=v&&typeof v==='object'?(v as Record<string,unknown>)[part]:undefined;
  if(v===null||v===undefined||v==='')continue;
  if(Array.isArray(v)){if(!v.length)continue;return v.map(x=>x&&typeof x==='object'?['name','sha256'].map(k=>(x as Record<string,unknown>)[k]).filter(Boolean).join(' · SHA-256 ')||JSON.stringify(x):String(x)).join('\n');}
  return typeof v==='object'?JSON.stringify(v):String(v);}
 return '';
}

/** One incident timeline row from A3's {ts, event} entries (or older {ts, verdict|action|kind, agent}). */
export function timelineRow(t:Record<string,unknown>):{ts:number;who:string;what:string}{
 const ev=typeof t.event==='string'?t.event:'';const m=ev.match(/^(A[1-8])\s+([\w.-]+):\s*(.*)$/);
 if(m)return {ts:Number(t.ts),who:m[1],what:m[3]||m[2].replace(/_/g,' ')};
 if(ev)return {ts:Number(t.ts),who:/^(Detected|Last trusted)/.test(ev)?'Decision layer':/^Bedside/.test(ev)?'Staff':/^Alert /.test(ev)?'Alert':'Record',what:ev};
 return {ts:Number(t.ts),who:String(t.agent??t.by??'Decision layer'),what:t.verdict?`Verdict ${String(t.verdict).replace(/_/g,' ')}`:String(t.action??t.kind??'Event not described').replace(/_/g,' ')};
}
/** Evidence file facts from A3 ({name, bytes, path}) or a manual snapshot ({label, filename, size_bytes}). */
export function evidenceView(e:Record<string,unknown>){
 const file=String(e.filename??e.path??e.name??'').split('/').pop()||'';
 const title=typeof e.label==='string'?e.label:typeof e.name==='string'?e.name:e.kind?String(e.kind).replace(/_/g,' '):file||'Evidence file';
 return {title,file,size:typeof e.bytes==='number'?e.bytes:typeof e.size_bytes==='number'?e.size_bytes:null};
}
