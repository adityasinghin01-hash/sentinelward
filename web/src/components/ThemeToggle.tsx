import {useRef} from 'react';
import {flushSync} from 'react-dom';
import {Moon, Sun} from 'lucide-react';
import {applyTheme, routeTheme, useTheme} from '../lib/theme';
let transitionPending = false;
export function ThemeToggle({scope}: {scope?: 'app' | 'landing'}) {
  const theme = useTheme();
  const ref = useRef<HTMLButtonElement>(null);
  const toggle = () => {
    if (transitionPending) return;
    const next = theme === 'dark' ? 'light' : 'dark';
    const root = document.documentElement;
    const apply = () => flushSync(() => applyTheme(next, true));
    if (!document.startViewTransition || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { apply(); return; }
    const b = ref.current!.getBoundingClientRect();
    const x = b.left + b.width / 2, y = b.top + b.height / 2;
    const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    const duration = (scope ?? (routeTheme(location.pathname) === 'light' ? 'landing' : 'app')) === 'landing' ? 440 : 260;
    transitionPending = true;
    try {
      const vt = document.startViewTransition(apply);
      void vt.ready.then(() => {
        root.animate({clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`]},
          {duration, easing: 'cubic-bezier(.22,1,.36,1)', pseudoElement: '::view-transition-new(root)'});
      }).catch(() => {});
      void vt.finished.then(() => {transitionPending = false;}, () => {transitionPending = false;});
    } catch { transitionPending = false; apply(); }
  };
  return <button ref={ref} className="icon-button theme-toggle" onClick={toggle} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} appearance`} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} appearance`}>
    {theme === 'dark' ? <Sun size={18} aria-hidden="true"/> : <Moon size={18} aria-hidden="true"/>}
  </button>;
}
