import {lazy, Suspense, useEffect, useLayoutEffect} from 'react';
import {Navigate, Route, Routes, useLocation} from 'react-router-dom';
import {useWard} from './lib/store';
import {initializeTheme} from './lib/theme';
import {Toaster} from './components/notifications';
import {RouteLoading} from './components/RouteLoading';
import {LoginPage} from './pages/Login';
import {LandingPage} from './pages/Landing';

// Public pages stay eager; clinical screens and their controls load only on demand.
const Shell = lazy(() => import('./components/Shell').then(m => ({default: m.Shell})));
const DevUI = import.meta.env.DEV ? lazy(() => import('./pages/DevUI')) : null;
const WardPage = lazy(() => import('./pages/Ward').then(m => ({default: m.WardPage})));
const BedPage = lazy(() => import('./pages/Bed').then(m => ({default: m.BedPage})));
const AlertsPage = lazy(() => import('./pages/Alerts').then(m => ({default: m.AlertsPage})));
const SecurityPage = lazy(() => import('./pages/Security').then(m => ({default: m.SecurityPage})));
const IncidentListPage = lazy(() => import('./pages/Incident').then(m => ({default: m.IncidentListPage})));
const IncidentPage = lazy(() => import('./pages/Incident').then(m => ({default: m.IncidentPage})));
const ReportPage = lazy(() => import('./pages/Report').then(m => ({default: m.ReportPage})));
const CensusPage = lazy(() => import('./pages/Census').then(m => ({default: m.CensusPage})));
const TicketsPage = lazy(() => import('./pages/Tickets').then(m => ({default: m.TicketsPage})));
const BriefingPage = lazy(() => import('./pages/Briefing').then(m => ({default: m.BriefingPage})));
const LogPage = lazy(() => import('./pages/Log').then(m => ({default: m.LogPage})));
const DemoPage = lazy(() => import('./pages/Demo').then(m => ({default: m.DemoPage})));

export function App() {
  const location=useLocation();
  useLayoutEffect(()=>initializeTheme(location.pathname),[location.pathname]);
  const setSession = useWard(s => s.setSession);
  useEffect(() => {
    const expired = () => setSession(null);
    window.addEventListener('sw:session-expired', expired);
    return () => window.removeEventListener('sw:session-expired', expired);
  }, [setSession]);
  return (
    <><Toaster/><Suspense fallback={<RouteLoading fullPage />}><Routes>
      {DevUI && <Route path="/dev/ui" element={<Suspense fallback={<RouteLoading fullPage />}><DevUI/></Suspense>}/> }
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
    </Routes></Suspense></>
  );
}
