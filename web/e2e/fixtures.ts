// Test-only fixtures shaped exactly like backend/API.md responses. Never used by production code.
const now = Date.now();
const wave = (n: number, f: (i: number) => number) => Array.from({length: n}, (_, i) => +f(i).toFixed(3));
const ecg = wave(150, i => (i % 25 === 0 ? 1.2 : i % 25 === 1 ? -0.4 : Math.sin(i / 4) * 0.08));
const ppg = wave(150, i => Math.sin((i % 25) / 25 * Math.PI) ** 2);
const flat = wave(150, () => 0);

function bed(id: number, over: Record<string, unknown> = {}) {
  const bed_id = `B${String(id).padStart(2, '0')}`;
  return {
    bed_id, device_id: `MON-${String(id).padStart(2, '0')}`, patient: {initials: 'A.K.', age: 60 + id, sex: id % 2 ? 'F' : 'M'},
    verdict: 'NORMAL', priority: 'none', trust_score: 92, is_trusted: true, connected: true, isolated: false,
    reason: 'All applicable live checks are clear', requested_action: 'Continue monitoring', acknowledged: false,
    last_updated_at: now - 500, vitals: {hr: 70 + id, spo2: 97, systolic: 118, diastolic: 74}, waveform: {ecg, ppg},
    last_trusted: {captured_at: now - 500, vitals: {hr: 70 + id, spo2: 97, systolic: 118, diastolic: 74}, waveform: {ecg, ppg}},
    display: 'live', offline_since: null, manual: null, last_bedside_check: null,
    assignment: {clinician_id: 'staff:priya', staff_id: 'staff:priya', status: 'assigned', ts: null, by: null}, nurse_call: null, ...over,
  };
}
const goodAt = now - 184_000;
export const beds = [
  bed(1), bed(2),
  bed(3, {verdict: 'EMERGENCY', priority: 'high', trust_score: 71, vitals: {hr: 168, spo2: 86, systolic: 78, diastolic: 44}, reason: 'Heart, pulse and pressure worsen together', requested_action: 'Go to the bed now'}),
  bed(4, {verdict: 'LOOSE_SENSOR', priority: 'low', trust_score: 64, waveform: {ecg, ppg: flat}, requested_action: 'Refit the finger clip'}),
  bed(5, {verdict: 'DRIFTING', priority: 'medium', trust_score: 80}),
  bed(6),
  bed(7, {verdict: 'BOTH', priority: 'high', trust_score: 18, is_trusted: false, display: 'last_trusted', vitals: {hr: 0, spo2: 99, systolic: 120, diastolic: 80},
          last_trusted: {captured_at: goodAt, vitals: {hr: 112, spo2: 91, systolic: 96, diastolic: 58}, waveform: {ecg, ppg}},
          reason: 'Replayed signal on a deteriorating patient', requested_action: 'GO NOW · check by hand', isolated: true}),
  bed(8), bed(9, {verdict: 'UNSURE', priority: 'medium', trust_score: 55}), bed(10), bed(11), bed(12),
];
const score = (model: string, s: number | null, reason: string, extra: Record<string, unknown> = {}) =>
  ({v: 1, type: 'score', bed_id: 'B07', model, model_version: `${model}-live`, window_start: now - 10_000, window_s: 10, score: s, label: model, reason, extra});
export const bedDetail = {
  ...beds[6],
  scores: {
    M1: score('M1', 0.04, 'ECG and pulse signals are usable'),
    M2: score('M2', 0.91, 'Pulse and pressure falling together, as in a real emergency'),
    M3: score('M3', 0.88, 'Beat-to-pulse delay jumped from 205 ms to 412 ms', {pat_ms: 412, baseline_pat_ms: 205, ecg_rate_bpm: 112, ppg_rate_bpm: 64}),
    M4: score('M4', 0.998, 'Signal matches a window recorded 3 minutes earlier'),
    M5: score('M5', 0.93, 'Second sender and repeated sequence numbers', {features: {msg_rate: 2.1, seq_gap_count: 0, seq_dup_count: 14}}),
    M6: score('M6', null, 'No arterial line in this window'),
  },
  recent_verdicts: Array.from({length: 6}, (_, i) => ({v: 1, type: 'verdict', bed_id: 'B07', ts: now - i * 5000, window_start: now - i * 5000 - 10_000,
    verdict: i < 4 ? 'BOTH' : 'TAMPERING', priority: 'high', confidence: 0.93, trust: 0.18, last_trusted_ts: goodAt,
    reasons: ['Replay check: signal matches a window recorded 3 minutes earlier', 'Body check: heart and pulse disagree', 'Pressure falling: possible real deterioration'], scores: {}})),
  device: {online: true, isolated: true, isolated_since: now - 120_000, last_seen_ts: now - 1000},
  open_alerts: [] as unknown[],
};
export const history = {bed_id: 'B07', points: Array.from({length: 1800}, (_, i) => ({
  ts: now - (1800 - i) * 1000, hr: 80 + Math.sin(i / 90) * 6 + (i > 1500 ? (i - 1500) / 10 : 0), spo2: 97 - (i > 1500 ? (i - 1500) / 60 : 0), rr: 18,
  sys: 120 - (i > 1500 ? (i - 1500) / 12 : 0), dia: 76, map: null, abp_mean: null, verdict: i > 1616 ? 'BOTH' : 'NORMAL', trusted: i < 1616}))};
export const alerts = [
  {v: 1, type: 'alert', alert_id: 'al_b07', ts: now - 42_000, bed_id: 'B07', verdict: 'BOTH', priority: 'high', text: 'Bed 7 — GO NOW. Do not trust the screen numbers.', to: ['staff:priya', 'staff:tom'], ladder_step: 2, status: 'escalated', acked_by: null, acked_ts: null},
  {v: 1, type: 'alert', alert_id: 'al_b03', ts: now - 95_000, bed_id: 'B03', verdict: 'EMERGENCY', priority: 'high', text: 'Bed 3 — possible heart emergency. Go now.', to: ['staff:priya'], ladder_step: 1, status: 'open', acked_by: null, acked_ts: null},
  {v: 1, type: 'alert', alert_id: 'al_b05', ts: now - 300_000, bed_id: 'B05', verdict: 'DRIFTING', priority: 'medium', text: 'Bed 5 — blood pressure may be drifting (12 mmHg off the cuff).', to: ['staff:tom'], ladder_step: 1, status: 'open', acked_by: null, acked_ts: null},
  {v: 1, type: 'alert', alert_id: 'al_b04', ts: now - 600_000, bed_id: 'B04', verdict: 'LOOSE_SENSOR', priority: 'low', text: 'Bed 4 — finger sensor loose. False alarm silenced.', to: ['staff:priya'], ladder_step: 1, status: 'acked', acked_by: 'staff:priya', acked_ts: now - 580_000},
];
const act = (id: string, ago: number, actor: string, code: string, action: string, undoable = false, mode = 'automatic') =>
  ({id, occurred_at: now - ago, actor, action_code: code, action, bed_id: 'B07', device_id: 'MON-07', approved_by: null, mode, undoable, references_action_id: null});
export const actions = {actions: [
  act('act_rep', 60_000, 'A5', 'draft_report', 'CERT-In report drafted; 6-hour clock started'),
  act('act_ev', 100_000, 'A3', 'snapshot_files', 'Evidence frozen: readings, network log, verdict log'),
  act('act_iso', 120_000, 'A2', 'disable_client', 'MON-07 cut off from the ward network', true),
  act('act_alert', 130_000, 'A1', 'send_message', 'Nurse Priya alerted on Telegram'),
  act('act_sam', 30_000, 'staff:sam', 'capture_evidence', 'Manual snapshot of B07', false, 'person'),
]};
export const devices = beds.map(b => ({device_id: b.device_id, bed_id: b.bed_id, online: true, isolated: b.bed_id === 'B07', isolated_since: b.bed_id === 'B07' ? now - 120_000 : null, last_seen_ts: now - 900,
  net: {v: 1, type: 'net_features', device_id: b.device_id, window_start: now - 5000, window_s: 5, msgs_per_s: b.bed_id === 'B07' ? 2.1 : 1.0, bytes_per_s: 410, iat_mean_ms: 1000, iat_std_ms: b.bed_id === 'B07' ? 3 : 24,
        payload_mean: 410, payload_std: 20, senders: b.bed_id === 'B07' ? 2 : 1, connects_per_s: 0, malformed: 0, seq_gaps: 0, seq_repeats: b.bed_id === 'B07' ? 14 : 0, stale_ms: 900}}));
export const network = Array.from({length: 120}, (_, i) => ({...devices[6].net, window_start: now - (120 - i) * 5000, msgs_per_s: i > 90 ? 2 + Math.random() * 0.3 : 1}));
const sha = (s: string) => s.repeat(64).slice(0, 64);
export const incident = {record_id: 'inc_7', kind: 'incident', ts: now - 125_000, by: 'A3', version: 3, updated_ts: null, updated_by: null, data: {
  bed_id: 'B07', device_id: 'MON-07', attack_type: 'replay_attack', status: 'verified_available_context', affected_beds: ['B07'], pcap_available: false,
  timeline: [{ts: now - 125_000, kind: 'verdict', verdict: 'TAMPERING'}, {ts: now - 110_000, kind: 'verdict', verdict: 'BOTH'}],
  evidence: [
    {kind: 'readings', path: '/srv/evidence/inc_7/readings.jsonl', sha256: sha('a3f9c2'), size_bytes: 48213, available: true, source: 'accepted MQTT message transcript; not PCAP', verified: true},
    {kind: 'network_log', path: '/srv/evidence/inc_7/network_log.jsonl', sha256: sha('7be01d'), size_bytes: 9120, available: true, source: 'accepted MQTT message transcript; not PCAP', verified: true},
    {kind: 'verdict_log', path: '/srv/evidence/inc_7/verdict_log.jsonl', sha256: sha('c0ffee'), size_bytes: 3388, available: true, source: 'decision layer output', verified: true},
  ]}};
const field = (value: string | null, status = 'observed', source = 'incident') => ({value, status: value ? status : 'missing', source: value ? source : 'unavailable'});
export const report = {record_id: 'rep_7', kind: 'report', ts: now - 60_000, by: 'A5', version: 1, updated_ts: null, updated_by: null, data: {
  incident_id: 'inc_7', status: 'needs_review', noticed_ts: now - 120_000, deadline_ts: now - 120_000 + 6 * 3600_000, provisional_notice: false,
  fields: {reporter_name: field(null), reporter_role: field('IT security', 'profile', 'hospital profile'), organisation: field('Demo Hospital, ICU-A', 'profile', 'hospital profile'),
    phone: field(null), mobile: field(null), email: field('security@demo-hospital.example', 'profile', 'hospital profile'), address: field(null),
    affected_entity: field('Bedside monitor MON-07, Bed 7'), sector: field('Healthcare', 'profile', 'hospital profile'), incident_type: field('Replay of patient-monitor data'),
    critical_to_mission: field('Yes'), ip_address: field(null), hostname: field('mon-07'), os_version: field(null), last_patched: field(null), vendor: field('SimMon'), model: field('SimMon v2'),
    location: field('ICU-A, Bed 7'), symptoms: field('Monitor reported normal values that matched a recording from 3 minutes earlier; a second sender used the device identity.'),
    actions_taken: field('Device cut off from the ward network by A2; evidence frozen and fingerprinted by A3; bedside nurse sent to check by hand.'),
    evidence_summary: field('3 files: readings, network log, verdict log (SHA-256 listed).')},
  evidence: incident.data.evidence, checklist: {facts_checked: false, evidence_reviewed: false, approved: false},
  narrative: {text: 'At 17:40 the monitor on Bed 7 began sending heart and oxygen readings that repeated an earlier recording. The body and network checks disagreed with the readings. The device was cut off and the nurse checked the patient by hand.', generator: 'granite'}}};
export const health = {ok: true, mqtt_connected: true, db_ok: true, storage: 'postgresql', durable: true, beds_online: 12, last_message_ts: now, invalid_messages: 0, pending_publications: 0, db_queued_rows: 0};
