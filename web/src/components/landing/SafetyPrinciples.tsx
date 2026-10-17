import {FileCheck2, HeartPulse, History, ScanLine} from 'lucide-react';

const REPO = 'https://github.com/adityasinghin01-hash/sentinelward/blob/main/';
const PRINCIPLES = [
  {icon: History, title: 'Keep a trusted reference',
    text: 'When a trusted snapshot exists, an untrusted bed keeps those values visible, marked as last trusted.',
    sources: ['backend/sw_api/state.py']},
  {icon: HeartPulse, title: 'Keep the emergency urgent',
    text: 'In B07, real VFIB on the attacked monitor raised a high BOTH alert that the cut-off did not cancel.',
    sources: ['docs/evidence/raw/wardrun-night/timeline_agentsN.txt']},
  {icon: ScanLine, title: 'Advice stays advice',
    text: 'M2 labels do not silence the monitor alarm, and the AI-chip second opinion cannot change a verdict, alert or action.',
    sources: ['docs/evidence/ML-RESULTS.md']},
  {icon: FileCheck2, title: 'A way back, a record kept',
    text: 'Device cut-offs have an Undo and an audit log; incident evidence files carry SHA-256 fingerprints.',
    sources: ['docs/evidence/SECURITY.md', 'agents_v2/sw_agents/agents/a3_evidence.py']},
];

export function SafetyPrinciples() {
  return (
    <section className="l-section l-safety" id="safety" aria-labelledby="l-safety-title">
      <div className="l-wrap">
        <p className="l-eyebrow" data-reveal>Safety principles</p>
        <h2 className="l-h2" id="l-safety-title" data-reveal>When data turns doubtful, available trusted values stay visible.</h2>
        <div className="l-cards four">
          {PRINCIPLES.map(principle => (
            <article key={principle.title} className="l-card l-safety-card" data-reveal data-tilt>
              <span className="l-card-icon"><principle.icon size={20} aria-hidden="true" /></span>
              <h3>{principle.title}</h3><p>{principle.text}</p>
              <p className="l-safety-source">source: {principle.sources.map((source, i) => <span key={source}>{i > 0 && ' · '}<a href={`${REPO}${source}`} target="_blank" rel="noreferrer">{source}</a></span>)}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
