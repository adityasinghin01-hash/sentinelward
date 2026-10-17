import {Link} from 'react-router-dom';
import {ArrowRight, HeartPulse, Unplug, ShieldAlert, Github, Activity, Lock, FileCheck2, Undo2, Server, Cpu, Boxes, Sparkles, Stethoscope, UserRound, ShieldCheck} from 'lucide-react';
import {ThemeToggle} from '../components/ThemeToggle';
import {useNow, useResource} from '../lib/hooks';
import type {Bed} from '../lib/types';
import {BedTile} from '../components/BedTile';
import {StateChip} from '../components/ui';
import {Hologram, ecgPath} from '../components/landing/Hologram';
import {useReveal} from '../lib/reveal';
import {RoleViews} from '../components/landing/RoleViews';
import {SafetyPrinciples} from '../components/landing/SafetyPrinciples';
import {SignalChips} from '../components/landing/SignalChips';
import {SiteFooter} from '../components/landing/SiteFooter';
import '../styles/landing2.css';

const REPO = 'https://github.com/adityasinghin01-hash/sentinelward';

const TRUTHS = [
  {icon: HeartPulse, tone: 'emergency', title: 'The patient', text: 'Heart, pulse and pressure change together and the network is clean.', act: 'The nurse is sent now; the alert climbs until someone answers.'},
  {icon: Unplug, tone: 'check', title: 'The sensor', text: 'The signal breaks but the body does not: a loose clip or a drifting line.', act: 'The false alarm is explained, the clip refitted, biomed gets a ticket.'},
  {icon: ShieldAlert, tone: 'security', title: 'A hacker', text: 'Numbers look calm but are replayed or injected over the network.', act: 'Available last trusted values stay visible; agents cut the monitor off and fingerprint the evidence.'},
];

const CHECKS = [
  ['Sensor usable', 'Is the signal clean enough to judge?'],
  ['Real emergency', 'Trained on real ICU alarms (PhysioNet)'],
  ['Body match', 'Do heart, pulse and pressure agree?'],
  ['Replay check', 'Is this a copy of older data?'],
  ['Network check', 'Multiple broker clients or a traffic flood?'],
  ['Drift', 'Is the pressure line slowly sliding?'],
];

const PROOF = [
  {n: '12 / 12', l: 'bed checks passed in night run N, agents on; earlier F1–F3: 12/11/11 of 12', s: 'docs/evidence/WARD-RUN.md'},
  {n: '0.862', l: 'held-out alarm score on PhysioNet CinC 2015 (old rule: 0.391)', s: 'docs/evidence/ML-RESULTS.md'},
  {n: '85.1%', l: 'false alarms marked likely false on CinC held-out (2.7% of true alarms missed); VTaC test: 84.1% (4.4% missed). Advice only; alarms still sound', s: 'docs/evidence/raw/fatigue.txt'},
  {n: '19.2 s', l: 'B07 real VF during a hack, F1–F3 median: attack start → bed untrusted, nurse told, monitor cut off', s: 'docs/evidence/WARD-RUN.md'},
  {n: '15 / 15', l: 'saved systemd hub security checks passed: per-device accounts, TLS 1.3, no anonymous access', s: 'docs/evidence/SECURITY.md'},
  {n: '96', l: 'beds in a 3-minute, one-CPU brain test; median/max tick 640.44/1,121.65 ms, 0 recorded drops; raw logs bundled', s: 'docs/evidence/SCALE.md'},
];

function Section({id, eyebrow, title, lead, children}: {id?: string; eyebrow: string; title: string; lead?: string; children: React.ReactNode}) {
  return (
    <section className="l-section" id={id}>
      <div className="l-wrap">
        <p className="l-eyebrow" data-reveal>{eyebrow}</p>
        <h2 className="l-h2" data-reveal>{title}</h2>
        {lead && <p className="l-lead" data-reveal>{lead}</p>}
        {children}
      </div>
    </section>
  );
}

export function LandingPage() {
  const now = useNow();
  const preview = useResource<{beds: Bed[]}>('/api/ward/preview', 3000);
  const beds = preview.data?.beds ?? [];
  const root = useReveal<HTMLDivElement>();
  return (
    <div className="landing" ref={root}>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="l-nav">
        <div className="l-wrap l-nav-inner">
          <Link to="/" className="l-brand" aria-label="SentinelWard home">
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M12 2.5 20 5.5v6.2c0 4.9-3.4 8.6-8 9.8-4.6-1.2-8-4.9-8-9.8V5.5z" fill="none" stroke="currentColor" strokeWidth="1.6"/><path d="M6.5 12.2h3l1.4-3 2.2 6 1.5-3h2.9" fill="none" stroke="var(--brand)" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></svg>
            SentinelWard
          </Link>
          <nav className="l-links" aria-label="Sections">
            <a href="#truths">The problem</a><a href="#how">How it works</a><a href="#proof">Proof</a><a href="#ibmz">IBM Z</a><a href="#trust">Security</a>
          </nav>
          <div className="l-nav-end">
            <ThemeToggle scope="landing" />
            <Link to="/login" className="l-btn l-btn-ghost">Sign in</Link>
          </div>
        </div>
      </header>

      <main id="main">
        <section className="l-hero">
          <div className="l-wrap l-hero-grid">
            <div className="l-hero-copy">
              <p className="l-eyebrow">Real-time AI on IBM LinuxONE · IBM Z Datathon 2026</p>
              <h1 className="l-h1">Patient, sensor,<br />or hacker?</h1>
              <p className="l-sub">SentinelWard checks every ICU bed every five seconds and tells the nurse whether an alarming reading is a real emergency, a faulty sensor or a hacked monitor. When data turns doubtful, available last trusted values stay on screen for a bedside check.</p>
              <div className="l-cta">
                <Link to="/login?role=nurse" className="l-btn l-btn-primary">Open the live ward <ArrowRight size={16} aria-hidden="true" /></Link>
                <a href="#how" className="l-btn l-btn-ghost">See how it works</a>
              </div>
              <ul className="l-hero-facts">
                <li><Activity size={14} aria-hidden="true" />12 beds live</li>
                <li><Server size={14} aria-hidden="true" />Runs on s390x</li>
                <li><Lock size={14} aria-hidden="true" />TLS 1.3 · per-device accounts</li>
              </ul>
            </div>
            <div className="l-hero-art"><Hologram /><SignalChips /></div>
          </div>
        </section>

        <section className="l-live" aria-label="Live ward preview">
          <div className="l-wrap">
            <div className="l-live-head" data-reveal>
              <span className="l-live-dot" aria-hidden="true" />Live from the ward on IBM LinuxONE, right now
              <span className="l-live-note">Demo environment · synthetic replay of real PhysioNet, MIMIC and VitalDB recordings</span>
            </div>
            <div className="l-live-grid" data-reveal>
              {beds.length ? beds.slice(0, 4).map(b => <BedTile key={b.bed_id} bed={b} now={now} mini />) :
                Array.from({length: 4}, (_, i) => <div key={i} className="skeleton-tile" />)}
            </div>
          </div>
        </section>

        <Section id="truths" eyebrow="The problem" title="One alarming number. Three different truths."
                 lead="Most monitor alarms are false: studies report 86 to 99.5 per cent. Nurses learn to tune them out, and a hacked monitor can hide a dying patient behind calm numbers.">
          <div className="l-cards three">
            {TRUTHS.map((t, i) => (
              <article key={t.title} className={`l-card truth-${t.tone}`} data-reveal data-tilt style={{transitionDelay: `${i * 50}ms`}}>
                <span className="l-card-icon"><t.icon size={20} aria-hidden="true" /></span>
                <h3>{t.title}</h3>
                <p>{t.text}</p>
                <p className="l-card-act">{t.act}</p>
              </article>
            ))}
          </div>
          <p className="l-cite" data-reveal>Source: Sowan et al., <a href="https://nursing.jmir.org/2021/1/e20584/PDF" target="_blank" rel="noreferrer">JMIR Nursing 2021</a>.</p>
        </Section>

        <Section id="how" eyebrow="How it works" title="Signal, verify, respond." lead="Every five seconds, for every bed, on one IBM LinuxONE server.">
          <div className="l-steps">
            <article className="l-step" data-reveal>
              <span className="l-step-n">1</span><h3>Signal</h3>
              <p>Each monitor streams heart, pulse, oxygen and pressure through a locked-down hub. A network witness counts broker client IDs per bed topic; it does not prove each frame’s physical sender.</p>
              <div className="l-mini l-mini-wave"><svg viewBox="0 0 320 90" preserveAspectRatio="none" aria-hidden="true"><path d={ecgPath()} /></svg></div>
            </article>
            <article className="l-step" data-reveal style={{transitionDelay: '50ms'}}>
              <span className="l-step-n">2</span><h3>Verify</h3>
              <p>Six independent checks ask whether the alarm is real, whether the body agrees and whether the data can be trusted at all.</p>
              <ul className="l-mini l-checks">{CHECKS.map(([n, d]) => <li key={n}><b>{n}</b><span>{d}</span></li>)}</ul>
            </article>
            <article className="l-step" data-reveal style={{transitionDelay: '100ms'}}>
              <span className="l-step-n">3</span><h3>Respond</h3>
              <p>One verdict per bed. Agents page the right nurse, cut off a hacked monitor, seal the evidence and write the shift briefing. Monitor cut-offs have an Undo.</p>
              <div className="l-mini l-respond">
                <StateChip state="BOTH" />
                <p>Bed 7 · go now · do not trust the numbers</p>
                <div className="l-respond-row"><span className="l-fake-btn primary">Acknowledge</span><span className="l-fake-btn"><Undo2 size={13} aria-hidden="true" />Undo cut-off</span></div>
              </div>
            </article>
          </div>
        </Section>

        <RoleViews />

        <Section id="proof" eyebrow="Proof" title="Measured, not promised." lead="Every number links to the file that holds it, with its limits written down.">
          <div className="l-proof">
            {PROOF.map((p, i) => (
              <div key={p.n} className="l-stat" data-reveal style={{transitionDelay: `${(i % 3) * 50}ms`}}>
                <b>{p.n}</b><p>{p.l}</p><a href={`${REPO}/blob/main/${p.s}`} target="_blank" rel="noreferrer">{p.s.replace('docs/evidence/', '')}</a>
              </div>
            ))}
          </div>
        </Section>

        <Section id="ibmz" eyebrow="IBM Z" title="Built on IBM LinuxONE, end to end." lead="Hospitals need decisions that stay up, stay private and stay on site. Everything that decides runs on the LinuxONE guest.">
          <div className="l-cards four">
            <article className="l-card" data-reveal><span className="l-card-icon"><Server size={20} aria-hidden="true" /></span><h3>Native s390x</h3><p>Models trained and served on LinuxONE; 96-bed short-run ticks had median/max 640.44/1,121.65 ms and 0 recorded drops. Raw logs are bundled.</p></article>
            <article className="l-card" data-reveal style={{transitionDelay: '50ms'}}><span className="l-card-icon"><Boxes size={20} aria-hidden="true" /></span><h3>Six containers</h3><p>Hub, database, API, brain, simulator and attacks form a separate Compose stack: four hardened app containers, authenticated service accounts and topic ACLs, plaintext internal MQTT, anonymous refused (137/137 checks). Agents and the witness run in the systemd ward.</p></article>
            <article className="l-card" data-reveal style={{transitionDelay: '100ms'}}><span className="l-card-icon"><Sparkles size={20} aria-hidden="true" /></span><h3>IBM Granite</h3><p>Writes the end-of-shift briefing on the box. Its numbers are checked against the ward's own records, and the structured facts sit beside it.</p></article>
            <article className="l-card" data-reveal style={{transitionDelay: '150ms'}}><span className="l-card-icon"><Cpu size={20} aria-hidden="true" /></span><h3>Telum II on-chip AI</h3><p>A second-opinion model on the z17 AI accelerator, shown only. In run N it scored the B03, B04 and B07 alarms; it is not guaranteed for every alarm and showed no speed advantage.</p></article>
          </div>
        </Section>

        <Section id="trust" eyebrow="Security and trust" title="Built for review and audit." lead="A trust layer has to be trustworthy itself.">
          <ul className="l-trust">
            <li data-reveal><Lock size={18} aria-hidden="true" /><div><b>Secured systemd hub</b><span>Every monitor has its own account and topic; TLS 1.3; anonymous access refused.</span></div></li>
            <li data-reveal><Undo2 size={18} aria-hidden="true" /><div><b>Undoable actions</b><span>Monitor cut-offs, acknowledgements and watch levels are logged with who, when and why, with Undo where supported.</span></div></li>
            <li data-reveal><FileCheck2 size={18} aria-hidden="true" /><div><b>Sealed evidence</b><span>Up to ten minutes of buffered verdicts, scores and events at incident opening, fingerprinted with SHA-256. Raw waveforms are not sealed by A3.</span></div></li>
            <li data-reveal><Activity size={18} aria-hidden="true" /><div><b>Speaks hospital</b><span>Authenticated read-only HL7 FHIR R4 subset export; no EHR connection has been demonstrated.</span></div></li>
          </ul>
        </Section>

        <SafetyPrinciples />

        <section className="l-section l-signin" id="signin">
          <div className="l-wrap">
            <h2 className="l-h2" data-reveal>See it working.</h2>
            <p className="l-lead" data-reveal>Pick a role and open the live ward. No account needed for the demo.</p>
            <div className="l-roles">
              <Link to="/login?role=nurse" className="l-role" data-reveal data-tilt><Stethoscope size={22} aria-hidden="true" /><b>Nurse</b><span>The ward, alerts and bedside checks</span><ArrowRight size={16} aria-hidden="true" /></Link>
              <Link to="/login?role=doctor" className="l-role" data-reveal data-tilt style={{transitionDelay: '50ms'}}><UserRound size={22} aria-hidden="true" /><b>Doctor</b><span>Census, trends and the evidence</span><ArrowRight size={16} aria-hidden="true" /></Link>
              <Link to="/login?role=it" className="l-role" data-reveal data-tilt style={{transitionDelay: '100ms'}}><ShieldCheck size={22} aria-hidden="true" /><b>IT security</b><span>Devices, cut-offs and incident reports</span><ArrowRight size={16} aria-hidden="true" /></Link>
            </div>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
