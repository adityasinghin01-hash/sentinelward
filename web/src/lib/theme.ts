import {useMemo, useSyncExternalStore} from 'react';
export type Theme = 'light' | 'dark';
export const THEME_EVENT = 'sw-theme-change';
export const THEME_STORAGE_KEY = 'sw.theme';
export function savedTheme(): Theme | null {
  try { const value = localStorage.getItem(THEME_STORAGE_KEY); return value === 'light' || value === 'dark' ? value : null; } catch { return null; }
}
export function routeTheme(path: string): Theme { return path === '/' || path.startsWith('/login') ? 'light' : 'dark'; }
export function applyTheme(theme: Theme, persist = false) {
  document.documentElement.dataset.theme = theme;
  if (persist) { try { localStorage.setItem(THEME_STORAGE_KEY, theme); } catch { /* unavailable storage never blocks appearance */ } }
  window.dispatchEvent(new CustomEvent(THEME_EVENT, {detail: {theme}}));
}
export function initializeTheme(path = location.pathname) { applyTheme(savedTheme() ?? routeTheme(path)); }
function subscribe(onChange: () => void) {
  window.addEventListener(THEME_EVENT, onChange);
  return () => window.removeEventListener(THEME_EVENT, onChange);
}
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, () => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light', () => 'light');
}
export const waveTokenNames = ['--wave-ecg','--wave-pleth','--wave-abp','--wave-grid','--wave-frozen'] as const;
export function readThemeTokens() {
  const styles = getComputedStyle(document.documentElement);
  return Object.fromEntries(waveTokenNames.map(name => [name, styles.getPropertyValue(name).trim()])) as Record<typeof waveTokenNames[number], string>;
}
/** Canvas users redraw when the root theme changes; sample/frozen state remains owned by the chart. */
export function useThemeTokens() { const theme = useTheme(); return useMemo(readThemeTokens, [theme]); }
export function seriesColour(label: string, tokens: ReturnType<typeof readThemeTokens>) {
  return /spo|pleth|oxygen/i.test(label) ? tokens['--wave-pleth'] : /bp|pressure|abp/i.test(label) ? tokens['--wave-abp'] : tokens['--wave-ecg'];
}
