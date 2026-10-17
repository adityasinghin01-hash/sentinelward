import {Suspense, useEffect} from 'react';
import type {ReactNode} from 'react';
import {Navigate, NavLink, useLocation, useNavigate} from 'react-router-dom';
import {AlertTriangle, LogOut, Radio, ShieldAlert, WifiOff, LockKeyhole, UserRound, ChevronDown} from 'lucide-react';
import {useWard, connectWard} from '../lib/store';
import {canOpen, openAlerts, roleHomes, roleNames, time, age} from '../lib/domain';
import type {AgentRecord} from '../lib/types';
import {useNow, useResource} from '../lib/hooks';
import {api} from '../lib/api';
import {Tip, Menu, MenuItem, MenuCheckboxItem, MenuLabel, MenuSeparator, TooltipProvider, toast, humanName} from './ui';
import {ThemeToggle} from './ThemeToggle';
import {RouteLoading} from './RouteLoading';

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
  const hidden = useWard(s => s.hidden);
  const setHidden = useWard(s => s.setHidden);
  const navigate = useNavigate();
  const logout = async () => {
    try { await api('/api/session', {method: 'DELETE'}); } catch { /* the session ends locally either way */ }
    setSession(null);
    navigate('/login');
    toast('Signed out');
  };
  const live = connection === 'live';
  return (
    <header className="topbar">
      <div className="brand">
        <LogoMark />
        <span>SentinelWard</span>
        <Tip text="The ward this station is watching."><span className="unit">ICU-A</span></Tip>
      </div>
      <nav aria-label="Screens">
        {NAV.filter(n => canOpen(session.role, n.page)).map(n => (
          <NavLink key={n.to} to={n.to} title={n.hint}>{n.label}</NavLink>
        ))}
      </nav>
      <div className="topbar-right">
        <Tip text={live ? 'Live: readings are arriving from the ward hub now.' : 'Stream interrupted. Last received information stays visible while the station reconnects.'}>
          <span className={`live-pill ${live ? 'is-live' : 'is-down'}`}>
            {live ? <Radio size={13} aria-hidden="true" /> : <WifiOff size={13} aria-hidden="true" />}
            {live ? 'LIVE' : 'RECONNECTING'}<span className="live-age mono">{receivedAt ? `${age(receivedAt, now)} ago` : 'awaiting signal'}</span>
          </span>
        </Tip>
        <span className="clock mono" title="Local time on this station">{time(now, true)}</span>
        {hidden && <span className="privacy-chip" title="Identity hidden"><LockKeyhole size={13} aria-hidden="true"/><span className="sr-only">Identity hidden</span></span>}
        <ThemeToggle scope="app"/>
        <Menu label="Account" trigger={<button className="account-trigger" aria-label={`Account: ${humanName(session.display_name || session.name)}`}><UserRound size={16} aria-hidden="true"/><span>{humanName(session.display_name || session.name)}</span><ChevronDown size={12} aria-hidden="true"/></button>}>
          <MenuLabel className="menu-label"><strong>{humanName(session.display_name || session.name)}</strong><small>{roleNames[session.role]}</small></MenuLabel>
          <MenuSeparator className="menu-separator"/>
          <MenuCheckboxItem checked={hidden} onCheckedChange={()=>setHidden()}>Hide names</MenuCheckboxItem>
          <MenuSeparator className="menu-separator"/>
          <MenuItem onSelect={()=>void logout()}><LogOut size={15} aria-hidden="true"/>Log out</MenuItem>
        </Menu>
      </div>
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
  const high = openAlerts(alerts).filter(a => a.verdict === 'EMERGENCY' || a.verdict === 'BOTH');
  if (!high.length) return null;
  const beds = [...new Set(high.map(a => a.bed_id))];
  return (
    <div className="alarm-strip" role="alert">
      <AlertTriangle size={15} aria-hidden="true" />
      <strong>EMERGENCY</strong>
      <div className="alarm-beds">{beds.map(bed=><NavLink key={bed} to={`/bed/${bed}`} aria-label={`Open ${bed}`} title={`Open ${bed}: emergency${high.some(a=>a.bed_id===bed&&a.verdict==='BOTH')?' · monitor hacked':''}`}>{bed}</NavLink>)}</div>
      {role === 'biomedical' && <span>Nurses alerted</span>}
    </div>
  );
}

export function Shell({page, children}: {page: string; children: ReactNode}) {
  const session = useWard(s => s.session);
  const location = useLocation();
  useEffect(() => (session ? connectWard() : undefined), [session]);
  if (!session) return <Navigate to="/login" replace state={{from: location.pathname}} />;
  if (!canOpen(session.role, page)) return <Navigate to={roleHomes[session.role]} replace />;
  return (
    <TooltipProvider><div className="app">
      <a className="skip-link" href="#main">Skip to content</a>
      <TopBar />
      <AlarmStrip />
      <main id="main" tabIndex={-1}><Suspense fallback={<RouteLoading />}>{children}</Suspense></main>
    </div></TooltipProvider>
  );
}

function LogoMark(){return <svg className="logo-mark" width="24" height="28" viewBox="0 0 24 28" fill="none" aria-hidden="true"><path d="M12 2 22 6v8c0 6-10 12-10 12S2 20 2 14V6L12 2Z" stroke="currentColor" strokeWidth="1.5"/><path d="M4 14h4l2-5 4 10 2-5h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}

