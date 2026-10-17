import {Link} from 'react-router-dom';
import {ThemeToggle} from '../components/ThemeToggle';
import {Activity, HeartPulse, ShieldAlert, Unplug, ArrowDown, Github} from 'lucide-react';
import {useNow, useResource} from '../lib/hooks';
import type {Bed} from '../lib/types';
import {BedTile} from '../components/BedTile';

const CASES = [
  {icon: HeartPulse, title: 'Real emergency', text: 'Heart, pulse and pressure worsen together and the network looks normal. The nurse is sent now, and the alert climbs a ladder until someone answers.'},
  {icon: Unplug, title: 'Loose or drifting sensor', text: 'The signal breaks but the body does not. The false alarm is silenced, the nurse is asked to refit the clip, and biomed gets a ticket.'},
  {icon: ShieldAlert, title: 'Hacker', text: 'Numbers look normal but are replayed or injected. The bed turns grey-striped, shows the last trusted values, IT cuts the device off, and the evidence is fingerprinted.'},
];

export function LandingPage() {
  const now = useNow();
  // Public, read-only preview of 4 beds; works without signing in.
  const preview = useResource<{beds: Bed[]}>('/api/ward/preview', 3000);
  const beds = preview.data?.beds ?? [];
  return (
    <div className="landing">
      <header className="landing-top">
        <div className="brand"><Activity size={18} aria-hidden="true" />SentinelWard</div>
        <div className="landing-account"><ThemeToggle scope="landing"/><Link to="/login" className="button-link">Log in</Link></div>
      </header>
      <main id="main">
        <section className="hero">
          <h1>Patient, sensor, or hacker?</h1>
          <p>Real-time AI on IBM LinuxONE that tells, for every hospital bed, whether a scary reading is real, a faulty sensor, or tampered data. The patient is never shown blank.</p>
          <div className="row-actions">
            <Link to="/login?role=nurse" className="button-link primary" title="Sign in as the central nurse and open the live ward.">Open the live ward</Link>
            <a href="#how" className="button-link ghost"><ArrowDown size={14} aria-hidden="true" /> How it works</a>
          </div>
        </section>
        <section className="mini-ward" aria-label="Live preview of four beds">
          <div className="mini-head">
            <span className="eyebrow">Live mini-ward</span>
            <span className="tiny">{preview.data ? 'Beds 1–4 from the demo ward, updated every few seconds. Identities hidden.' : preview.error ? '' : 'Connecting…'}</span>
          </div>
          {preview.error && !beds.length ? (
            <div className="offline-preview" role="status">
              <strong>Live demo offline</strong>
              <span>The ward server is not reachable right now. Sign in once it is back to see the live beds.</span>
            </div>
          ) : (
            <div className="bed-grid mini-grid">
              {(beds.length ? beds : []).map(b => <BedTile key={b.bed_id} bed={b} now={now} mini />)}
              {!beds.length && Array.from({length: 4}, (_, i) => <div key={i} className="bed-tile skeleton-tile" aria-hidden="true" />)}
            </div>
          )}
        </section>
        <section id="how" className="cases">
          {CASES.map(({icon: Icon, title, text}) => (
            <article key={title} className="case"><Icon size={20} aria-hidden="true" /><h2>{title}</h2><p>{text}</p></article>
          ))}
        </section>
      </main>
      <footer className="landing-foot">
        <span>Team TessNova · IBM Z Datathon 2026 · Theme 1: real-time AI decisions on IBM LinuxONE</span>
        <a href="https://github.com/adityasinghin01-hash/sentinelward" title="Project source code on GitHub"><Github size={14} aria-hidden="true" /> GitHub</a>
      </footer>
    </div>
  );
}
