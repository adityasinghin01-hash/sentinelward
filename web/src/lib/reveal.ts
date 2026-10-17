import {useEffect, useRef} from 'react';

// Landing-page scroll reveals (DESIGN-SPEC §3, research-codex C2).
// One IntersectionObserver per container; no scroll listeners. Nodes marked
// [data-reveal] start visible; only nodes below the fold get [data-reveal-pending]
// (hidden by CSS) and lose it the first time they enter the viewport.
export const REVEAL_OPTIONS: IntersectionObserverInit = {threshold: 0.08, rootMargin: '0px 0px -8% 0px'};

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Stagger for the i-th item of a group: 50 ms steps, capped at 150 ms. */
export function revealDelay(index: number): number {
  return Math.min(Math.max(0, index) * 50, 150);
}

export function useReveal<T extends HTMLElement = HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const nodes = Array.from(root.querySelectorAll<HTMLElement>('[data-reveal]'))
      .filter(n => n.dataset.revealed !== 'true');
    const show = (n: HTMLElement) => { n.removeAttribute('data-reveal-pending'); n.dataset.revealed = 'true'; };
    if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') {
      nodes.forEach(show);
      return;
    }
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const el = entry.target as HTMLElement;
        show(el);
        observer.unobserve(el);
      }
    }, REVEAL_OPTIONS);
    // Observer exists before anything is hidden; content already on screen is never hidden.
    const fold = window.innerHeight * 0.92;
    for (const n of nodes) {
      if (n.getBoundingClientRect().top < fold) { show(n); continue; }
      n.setAttribute('data-reveal-pending', '');
      observer.observe(n);
    }
    return () => {
      observer.disconnect();
      // StrictMode / unmount safety: never leave content hidden.
      nodes.forEach(n => n.removeAttribute('data-reveal-pending'));
    };
  }, []);
  return ref;
}
