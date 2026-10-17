import {Github} from 'lucide-react';
import {Link} from 'react-router-dom';

const REPO = 'https://github.com/adityasinghin01-hash/sentinelward';
const EVIDENCE = ['WARD-RUN', 'ML-RESULTS', 'SECURITY', 'SCALE', 'CONTAINERS'];
// Names and URLs copied from README.md, Sources / open-source.
const CREDITS = [
  ['PhysioNet/CinC Challenge 2015', 'https://physionet.org/content/challenge-2015/1.0.0/'],
  ['VTaC', 'https://physionet.org/content/vtac/1.0/'],
  ['MIMIC-III Waveform Database Matched Subset', 'https://physionet.org/content/mimic3wdb-matched/1.0/'],
  ['VitalDB', 'https://vitaldb.net/'],
  ['IBM Granite', 'https://github.com/ibm-granite'],
  ['Eclipse Mosquitto', 'https://mosquitto.org/'],
  ['PostgreSQL', 'https://www.postgresql.org/'],
  ['FastAPI', 'https://fastapi.tiangolo.com/'],
  ['React', 'https://react.dev/'],
];

export function SiteFooter() {
  return (
    <footer className="l-footer l-site-footer">
      <div className="l-wrap">
        <div className="l-footer-grid">
          <div className="l-footer-brand">
            <Link to="/" className="l-brand" aria-label="SentinelWard home">
              <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M12 2.5 20 5.5v6.2c0 4.9-3.4 8.6-8 9.8-4.6-1.2-8-4.9-8-9.8V5.5z" fill="none" stroke="currentColor" strokeWidth="1.6"/><path d="M6.5 12.2h3l1.4-3 2.2 6 1.5-3h2.9" fill="none" stroke="var(--brand)" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></svg>
              SentinelWard
            </Link>
            <p>Patient, sensor and security signals, in one ward view.</p>
            <p className="l-footer-team">Team TessNova · IBM Z Datathon 2026</p>
          </div>
          <nav aria-label="Product"><h2>Product</h2><ul>
            <li><Link to="/login?role=nurse">Live ward</Link></li>
            <li><a href="#how">How it works</a></li><li><a href="#proof">Proof</a></li>
            <li><a href="#ibmz">IBM Z</a></li><li><a href="#trust">Security</a></li>
          </ul></nav>
          <nav aria-label="Evidence"><h2>Evidence</h2><ul>
            {EVIDENCE.map(file => <li key={file}><a href={`${REPO}/blob/main/docs/evidence/${file}.md`} target="_blank" rel="noreferrer">{file}</a></li>)}
            <li><a href={`${REPO}/blob/main/docs/EXPLORE.md`} target="_blank" rel="noreferrer">Explore everything yourself</a></li>
          </ul></nav>
          <nav aria-label="Open source"><h2>Open source</h2><ul>
            {CREDITS.map(([name, href]) => <li key={name}><a href={href} target="_blank" rel="noreferrer">{name}</a></li>)}
          </ul></nav>
        </div>
        <div className="l-footer-bottom">
          <p>Demo environment · synthetic replay of real recordings · not a medical device</p>
          <a href={REPO} target="_blank" rel="noreferrer" aria-label="GitHub repository"><Github size={18} aria-hidden="true" /><span>GitHub</span></a>
        </div>
      </div>
    </footer>
  );
}
