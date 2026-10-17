import {useState} from 'react';
import {Check, CheckCircle2, Copy, Download, FileText} from 'lucide-react';
import {bytes, downloadName, evidenceView, time} from '../../lib/domain';
import {downloadJson} from '../../lib/api';
import {Button, Chip, toast} from '../ui';
import {actorName} from './actions';

type Evidence = Record<string, unknown>;
export function evidenceTitle(e: Evidence) {
  const name = String(e.label ?? e.name ?? e.filename ?? e.path ?? e.kind ?? '').toLowerCase();
  if (/message|reading|signal|transcript/.test(name)) return 'Signal record';
  if (/verdict|decision/.test(name)) return 'Decision record';
  if (/timeline/.test(name)) return 'Event timeline';
  if (/network|pcap/.test(name)) return 'Network record';
  if (/snapshot|bed/.test(name)) return 'Bed snapshot';
  return typeof e.label === 'string' && !/[._/]/.test(e.label) ? e.label : 'Evidence file';
}
export function Fingerprint({value, name}: {value: string; name: string}) {
  const [copiedValue, setCopiedValue] = useState('');
  const copied = copiedValue === value;
  if (!value) return <p className="tiny muted">Fingerprint not recorded</p>;
  const copy = async () => {
    try {await navigator.clipboard.writeText(value); setCopiedValue(value); toast.success('SHA-256 copied');}
    catch {toast.error('Could not copy. Select the fingerprint to copy it manually.');}
  };
  return <div className="fingerprint"><div><span className="fingerprint-label">SHA-256</span><code className="fingerprint-value">{value}</code></div>
    <Button size={36} variant="secondary" onClick={() => void copy()} aria-label={`Copy SHA-256 for ${name}`}>
      {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}{copied ? 'Copied' : 'Copy'}
    </Button></div>;
}
export function EvidenceRecord({e, incidentId, download = true}: {e: Evidence; incidentId: string; download?: boolean}) {
  const view = evidenceView(e);
  const title = evidenceTitle(e);
  const hasContent = e.content !== undefined;
  return <li className="evidence pages-evidence">
    <div className="evidence-head"><FileText size={16} aria-hidden="true" /><strong>{title}</strong>
      {e.verified === true && <Chip><CheckCircle2 size={13} aria-hidden="true" />Verified</Chip>}
      {e.available === false && <Chip>No data captured</Chip>}
    </div>
    <p className="tiny muted">{view.size === null ? 'Size not recorded' : bytes(view.size)}{e.captured_at ? ` · captured ${time(Number(e.captured_at), true)}` : ''}{e.captured_by ? ` · ${actorName(String(e.captured_by))}` : ''}</p>
    <Fingerprint value={typeof e.sha256 === 'string' ? e.sha256 : ''} name={title} />
    <div className="evidence-record-actions">
      {download && <Button size={36} variant="ghost" onClick={() => downloadJson(downloadName(incidentId, view.file || 'evidence'), hasContent ? e.content : e)}><Download size={14} aria-hidden="true" />{hasContent ? 'Download' : 'Download record'}</Button>}
      <details className="record-details"><summary>File details</summary><div className="record-original"><pre>{JSON.stringify(e, null, 2)}</pre></div></details>
    </div>
  </li>;
}
