import {useEffect} from 'react';
import type {ReactNode} from 'react';
import {Navigate, NavLink, Route, Routes, useLocation, useNavigate} from 'react-router-dom';
import {Activity, AlertTriangle, LogOut, Radio, ShieldAlert, WifiOff} from 'lucide-react';
import {useWard, connectWard} from './lib/store';
import {canOpen, openAlerts, roleHomes, roleNames, time} from './lib/domain';
import type {AgentRecord} from './lib/types';
import {useNow, useResource} from './lib/hooks';
import {api} from './lib/api';
import {Tip} from './components/ui';
import {LoginPage} from './pages/Login';
import {WardPage} from './pages/Ward';
import {BedPage} from './pages/Bed';
import {AlertsPage} from './pages/Alerts';
import {SecurityPage} from './pages/Security';
import {IncidentListPage, IncidentPage} from './pages/Incident';
import {ReportPage} from './pages/Report';
import {LandingPage} from './pages/Landing';
import {CensusPage} from './pages/Census';
import {TicketsPage} from './pages/Tickets';
import {BriefingPage} from './pages/Briefing';
import {LogPage} from './pages/Log';
import {DemoPage} from './pages/Demo';

// Every screen except landing and login needs a session, and each role only sees its own screens.
const NAV: {page: string; to: string; label: string; hint: string}[] = [
  {page: 'ward', to: '/ward', label: 'Ward', hint: 'All beds at a glance: who needs someone now, and why.'},
  {page: 'alerts', to: '/alerts', label: 'Alerts', hint: 'Open alerts and their escalation ladder.'},
  {page: 'census', to: '/census', label: 'Census', hint: 'Doctor / tele-ICU list of occupied beds by priority.'},
  {page: 'security', to: '/security', label: 'Security', hint: 'Devices, network witness, cut-off and undo (IT).'},
  {page: 'incident', to: '/incident', label: 'Incidents', hint: 'Security incidents, evidence and CERT-In report drafts (IT).'},
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

// R8 Part D: any high alarm shows on every clinical screen (Ward included), so nothing is missed.
// IT screens get their own strip for open security incidents instead: clinical alarms are not shown to IT.
function ItStrip() {
  const incidents = useResource<AgentRecord[]>('/api/incidents', 8000);
  const open = (incidents.data ?? []).filter(r => !['resolved', 'closed'].includes(String(r.data.status)));
  if (!open.length) return null;
  const first = open[0];
  return (
    <div className="it-strip" role="status">
      <ShieldAlert size={15} aria-hidden="true" />
      <strong>SECURITY INCIDENT{open.length > 1 ? `S · ${open.length}` : ''}</strong>
      <span>{open.slice(0, 4).map(r => `${String(r.data.device_id ?? 'device')} (Bed ${String(r.data.bed_id ?? '—')}) ${String(r.data.status ?? 'open').replace(/_/g, ' ')}`).join(' · ')}</span>
      <NavLink to={`/incident/${encodeURIComponent(first.record_id)}`} title="Open the newest open incident: timeline, evidence and CERT-In draft.">Open incident</NavLink>
    </div>
  );
}

function AlarmStrip() {
  const alerts = useWard(s => s.alerts);
  const role = useWard(s => s.session?.role);
  const location = useLocation();
  const itScreen = role === 'it' || /^\/(security|incident)/.test(location.pathname);
  if (itScreen) return <ItStrip />;
  const high = openAlerts(alerts).filter(a => a.priority === 'high');
  if (!high.length) return null;
  const beds = [...new Set(high.map(a => a.bed_id))];
  return (
    <div className="alarm-strip" role="alert">
      <AlertTriangle size={15} aria-hidden="true" />
      <strong>HIGH ALARM</strong>
      <span>{role === 'biomedical' ? `${beds.join(', ')} affected · nurses alerted` : high.slice(0, 3).map(a => `${a.bed_id}: ${a.text}`).join(' · ')}</span>
      {role !== 'biomedical' && <NavLink to={`/bed/${beds[0]}`} title="Open the alarming bed.">Open {beds[0]}</NavLink>}
    </div>
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
      <AlarmStrip />
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
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/ward" element={<Shell page="ward"><WardPage /></Shell>} />
      <Route path="/bed/:bedId" element={<Shell page="bed"><BedPage /></Shell>} />
      <Route path="/alerts" element={<Shell page="alerts"><AlertsPage /></Shell>} />
      <Route path="/census" element={<Shell page="census"><CensusPage /></Shell>} />
      <Route path="/security" element={<Shell page="security"><SecurityPage /></Shell>} />
      <Route path="/incident" element={<Shell page="incident"><IncidentListPage /></Shell>} />
      <Route path="/incident/:incidentId" element={<Shell page="incident"><IncidentPage /></Shell>} />
      <Route path="/incident/:incidentId/report" element={<Shell page="incident"><ReportPage /></Shell>} />
      <Route path="/tickets" element={<Shell page="tickets"><TicketsPage /></Shell>} />
      <Route path="/briefing" element={<Shell page="briefing"><BriefingPage /></Shell>} />
      <Route path="/log" element={<Shell page="log"><LogPage /></Shell>} />
      <Route path="/demo" element={<Shell page="demo"><DemoPage /></Shell>} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
