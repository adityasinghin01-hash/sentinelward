import {useEffect} from 'react';
import type {ReactNode} from 'react';
import {Navigate, NavLink, Route, Routes, useLocation, useNavigate} from 'react-router-dom';
import {Activity, LogOut, Radio, WifiOff} from 'lucide-react';
import {useWard, connectWard} from './lib/store';
import {canOpen, roleHomes, roleNames, time} from './lib/domain';
import {useNow} from './lib/hooks';
import {api} from './lib/api';
import {Tip} from './components/ui';
import {LoginPage} from './pages/Login';
import {WardPage} from './pages/Ward';
import {PlaceholderPage} from './pages/Placeholder';

// Every screen except landing and login needs a session, and each role only sees its own screens.
const NAV: {page: string; to: string; label: string; hint: string}[] = [
  {page: 'ward', to: '/ward', label: 'Ward', hint: 'All beds at a glance: who needs someone now, and why.'},
  {page: 'alerts', to: '/alerts', label: 'Alerts', hint: 'Open alerts and their escalation ladder.'},
  {page: 'census', to: '/census', label: 'Census', hint: 'Doctor / tele-ICU list of occupied beds by priority.'},
  {page: 'security', to: '/security', label: 'Security', hint: 'Devices, network witness, cut-off and undo (IT).'},
  {page: 'tickets', to: '/tickets', label: 'Tickets', hint: 'Biomedical repair tickets for faulty or drifting sensors.'},
  {page: 'briefing', to: '/briefing', label: 'Briefing', hint: 'Shift handover and nurse alarm workload.'},
  {page: 'log', to: '/log', label: 'Action log', hint: 'Every automatic and staff action, with undo where possible.'},
  {page: 'demo', to: '/demo', label: 'Demo', hint: 'Run or reset the 20-minute ward script (operator).'},
];

function TopBar() {
  const session = useWard(s => s.session)!;
  const connection = useWard(s => s.connection);
  const receivedAt = useWard(s => s.receivedAt);
  const setSession = useWard(s => s.setSession);
  const now = useNow();
  const navigate = useNavigate();
  const logout = async () => {
    try { await api('/api/session', {method: 'DELETE'}); } catch { /* the session ends locally either way */ }
    setSession(null);
    navigate('/login');
  };
  const live = connection === 'live';
  return (
    <header className="topbar">
      <div className="brand">
        <Activity size={18} aria-hidden="true" />
        <span>SentinelWard</span>
        <Tip text="The ward this station is watching."><span className="unit">ICU-A</span></Tip>
      </div>
      <nav aria-label="Screens">
        {NAV.filter(n => canOpen(session.role, n.page)).map(n => (
          <NavLink key={n.to} to={n.to} title={n.hint}>{n.label}</NavLink>
        ))}
      </nav>
      <div className="topbar-right">
        <Tip text="Local time on this station.">
          <span className="clock mono">{time(now, true)}</span>
        </Tip>
        <Tip text={live ? 'Live: readings are arriving from the ward hub now.' : 'Not live: the screen keeps the last received data and reconnects automatically.'}>
          <span className={`live-pill ${live ? 'is-live' : 'is-down'}`}>
            {live ? <Radio size={13} aria-hidden="true" /> : <WifiOff size={13} aria-hidden="true" />}
            {live ? 'LIVE' : connection === 'connecting' ? 'CONNECTING' : 'OFFLINE'}
          </span>
        </Tip>
        <span className="who" title="Signed-in role">{roleNames[session.role]}</span>
        <button className="icon-button" onClick={() => void logout()} title="Sign out of this station">
          <LogOut size={15} aria-hidden="true" /><span className="sr-only">Sign out</span>
        </button>
      </div>
      {!live && receivedAt && (
        <div className="connection-banner" role="status">
          Connection lost · showing data from {time(receivedAt, true)} · reconnecting
        </div>
      )}
    </header>
  );
}

function Shell({page, children}: {page: string; children: ReactNode}) {
  const session = useWard(s => s.session);
  const location = useLocation();
  useEffect(() => (session ? connectWard() : undefined), [session]);
  if (!session) return <Navigate to="/login" replace state={{from: location.pathname}} />;
  if (!canOpen(session.role, page)) return <Navigate to={roleHomes[session.role]} replace />;
  return (
    <div className="app">
      <a className="skip-link" href="#main">Skip to content</a>
      <TopBar />
      <main id="main" tabIndex={-1}>{children}</main>
    </div>
  );
}

export function App() {
  const setSession = useWard(s => s.setSession);
  useEffect(() => {
    const expired = () => setSession(null);
    window.addEventListener('sw:session-expired', expired);
    return () => window.removeEventListener('sw:session-expired', expired);
  }, [setSession]);
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/ward" element={<Shell page="ward"><WardPage /></Shell>} />
      <Route path="/bed/:bedId" element={<Shell page="bed"><PlaceholderPage title="Bed detail" /></Shell>} />
      {NAV.filter(n => n.page !== 'ward').map(n => (
        <Route key={n.to} path={n.to} element={<Shell page={n.page}><PlaceholderPage title={n.label} /></Shell>} />
      ))}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
