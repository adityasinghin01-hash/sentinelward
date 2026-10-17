import {useState} from 'react';
import {useLocation, useNavigate, useSearchParams} from 'react-router-dom';
import {Activity, ShieldCheck, Stethoscope, Wrench, MonitorPlay, HeartPulse} from 'lucide-react';
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

  return (
    <main className="login" id="main">
      <section className="login-card" aria-labelledby="login-title">
        <div className="brand brand-large"><Activity size={22} aria-hidden="true" />SentinelWard</div>
        <h1 id="login-title">Choose your role</h1>
        <p className="login-lead">
          Patient, sensor, or hacker: every reading on this station comes with the evidence behind it.
          Each role sees only the screens and buttons it needs.
        </p>
        <div className="role-grid">
          {ROLES.map(({role, icon: Icon, does}) => (
            <button key={role} className={`role-card ${preset === role ? 'is-preset' : ''}`} autoFocus={preset === role} onClick={() => void signIn(role)} disabled={pending !== null}
                    aria-busy={pending === role}>
              <Icon size={20} aria-hidden="true" />
              <strong>{roleNames[role]}</strong>
              <span>{does}</span>
              {pending === role && <em>Signing in…</em>}
            </button>
          ))}
        </div>
        {error && <p className="login-error" role="alert">{error}</p>}
        <p className="login-foot">
          Demo mode: one-click role sign-in is on for judges. Real password sign-in (hashed passwords,
          lockout, session expiry) is built in and can replace it.
        </p>
      </section>
    </main>
  );
}
