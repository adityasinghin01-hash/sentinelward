import {useState} from 'react';
import {ThemeToggle} from '../components/ThemeToggle';
import {Link, useLocation, useNavigate, useSearchParams} from 'react-router-dom';
import {Activity, ShieldCheck, Stethoscope, Wrench, MonitorPlay, HeartPulse, ArrowRight, ArrowLeft, Lock} from 'lucide-react';
import type {Role, Session} from '../lib/types';
import {api} from '../lib/api';
import {roleHomes, roleNames} from '../lib/domain';
import {useWard} from '../lib/store';

const ROLES: {role: Role; icon: typeof Activity; does: string}[] = [
  {role: 'nurse', icon: HeartPulse, does: 'Watches every bed, answers alerts, records the bedside check.'},
  {role: 'doctor', icon: Stethoscope, does: 'Tele-ICU view: beds by priority, read-only evidence.'},
  {role: 'it', icon: ShieldCheck, does: 'Devices and network: cut off a suspect monitor, undo, incidents.'},
  {role: 'biomedical', icon: Wrench, does: 'Repair tickets for loose or drifting sensors.'},
  {role: 'operator', icon: MonitorPlay, does: 'Runs or resets the 20-minute demo ward script.'},
];

export function LoginPage() {
  const setSession = useWard(s => s.setSession);
  const navigate = useNavigate();
  const location = useLocation();
  const [pending, setPending] = useState<Role | null>(null);
  const [params] = useSearchParams();
  const preset = params.get('role'); // S0 "Open the live ward" pre-selects the central nurse
  const [error, setError] = useState('');

  const signIn = async (role: Role) => {
    setPending(role);
    setError('');
    try {
      const s = await api<Partial<Session>>('/api/session', {method: 'POST', body: JSON.stringify({role})});
      const session: Session = {
        token: s.token ?? '', role: (s.role as Role) ?? role,
        name: s.name ?? roleNames[role], display_name: s.display_name ?? s.name ?? roleNames[role],
      };
      setSession(session);
      const from = (location.state as {from?: string} | null)?.from;
      navigate(from && from !== '/login' ? from : roleHomes[session.role], {replace: true});
    } catch (e) {
      setError(`Sign-in failed: ${(e as Error).message}. Check that the ward server is running, then try again.`);
    } finally {
      setPending(null);
    }
  };

  const card = ({role, icon: Icon, does}: typeof ROLES[number], big: boolean) => (
    <button key={role} className={`role-card ${big ? 'role-big' : 'role-small'} ${preset === role ? 'is-preset' : ''}`} autoFocus={preset === role}
            onClick={() => void signIn(role)} disabled={pending !== null} aria-busy={pending === role}>
      <span className="role-icon"><Icon size={big ? 20 : 16} aria-hidden="true" /></span>
      <span className="role-text"><strong>{roleNames[role]}</strong><span>{does}</span></span>
      {pending === role ? <em>Signing in…</em> : <ArrowRight className="role-go" size={16} aria-hidden="true" />}
    </button>
  );
  return (
    <main className="login" id="main">
      <aside className="login-side" aria-hidden="false">
        <Link to="/" className="login-home"><ArrowLeft size={15} aria-hidden="true" />SentinelWard home</Link>
        <div className="login-side-body">
          <div className="login-mark"><Activity size={22} aria-hidden="true" /></div>
          <p className="login-quote">Patient, sensor,<br />or hacker?</p>
          <p className="login-side-text">Every reading on this station comes with the evidence behind it, and every action can be undone.</p>
        </div>
        <ul className="login-facts">
          <li><span>12</span>beds watched live</li>
          <li><span>6</span>independent checks per bed</li>
          <li><span>5 s</span>from signal to verdict</li>
        </ul>
      </aside>
      <section className="login-main" aria-labelledby="login-title">
        <div className="login-top"><ThemeToggle scope="landing" /></div>
        <div className="login-panel">
          <h1 id="login-title">Sign in to SentinelWard</h1>
          <p className="login-lead">Choose your role. Each role sees only the screens and buttons it needs.</p>
          <div className="role-list">{ROLES.slice(0, 3).map(r => card(r, true))}</div>
          <p className="role-more">Other roles</p>
          <div className="role-row">{ROLES.slice(3).map(r => card(r, false))}</div>
          {error && <p className="login-error" role="alert">{error}</p>}
          <p className="login-foot"><Lock size={13} aria-hidden="true" />Demo environment: one-click sign-in for judges, synthetic patients. Hashed-password sign-in with lockout and session expiry is built in and can replace it.</p>
        </div>
      </section>
    </main>
  );
}
