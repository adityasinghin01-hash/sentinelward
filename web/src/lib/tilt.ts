import {useEffect} from 'react';
import type {RefObject} from 'react';

/** Delegated, attribute-based tilt. One frame at a time; no scroll listener. */
export function useTilt(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    // The role section owns the landing interaction lifecycle, including sibling cards.
    const scope = ref.current?.closest<HTMLElement>('.landing') ?? ref.current;
    if (!scope || typeof window.matchMedia !== 'function') return;
    const pointer = window.matchMedia('(pointer: fine)');
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const cards = Array.from(scope.querySelectorAll<HTMLElement>('[data-tilt]'));
    let current: HTMLElement | null = null;
    let frame: number | null = null;
    let x = 0;
    let y = 0;
    const reset = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      if (!current) return;
      current.style.setProperty('--tilt-x', '0deg');
      current.style.setProperty('--tilt-y', '0deg');
      current.removeAttribute('data-tilt-hover');
      current = null;
    };
    const sync = () => {
      reset();
      for (const card of cards) card.toggleAttribute('data-tilt-ready', pointer.matches && !motion.matches);
    };
    const cardAt = (target: EventTarget | null) => {
      const card = target instanceof Element ? target.closest<HTMLElement>('[data-tilt]') : null;
      return card && scope.contains(card) ? card : null;
    };
    const move = (event: PointerEvent) => {
      if (!pointer.matches || motion.matches || event.pointerType === 'touch') return;
      const card = cardAt(event.target);
      if (!card) return;
      if (current !== card) { reset(); current = card; }
      x = event.clientX; y = event.clientY;
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        if (!current) return;
        const rect = current.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const mx = Math.min(1, Math.max(0, (x - rect.left) / rect.width));
        const my = Math.min(1, Math.max(0, (y - rect.top) / rect.height));
        current.style.setProperty('--tilt-x', `${(0.5 - my) * 8}deg`);
        current.style.setProperty('--tilt-y', `${(mx - 0.5) * 8}deg`);
        current.style.setProperty('--mx', `${mx * 100}%`);
        current.style.setProperty('--my', `${my * 100}%`);
        current.setAttribute('data-tilt-hover', '');
      });
    };
    const leave = (event: PointerEvent) => {
      if (current && !current.contains(event.relatedTarget instanceof Node ? event.relatedTarget : null)) reset();
    };
    sync();
    scope.addEventListener('pointermove', move, {passive: true});
    scope.addEventListener('pointerout', leave);
    pointer.addEventListener('change', sync);
    motion.addEventListener('change', sync);
    return () => {
      reset();
      scope.removeEventListener('pointermove', move);
      scope.removeEventListener('pointerout', leave);
      pointer.removeEventListener('change', sync);
      motion.removeEventListener('change', sync);
      for (const card of cards) {
        card.removeAttribute('data-tilt-ready');
        for (const property of ['--tilt-x', '--tilt-y', '--mx', '--my']) card.style.removeProperty(property);
      }
    };
  }, [ref]);
}
