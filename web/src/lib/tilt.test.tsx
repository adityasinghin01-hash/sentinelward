import {useRef} from 'react';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {useTilt} from './tilt';

let fine = true;
let reduced = false;
let frame: FrameRequestCallback | undefined;
function Cards() {
  const root = useRef<HTMLDivElement>(null);
  useTilt(root);
  return <div ref={root}><a href="#proof" data-tilt>Proof</a><button data-tilt>Other card</button></div>;
}
beforeEach(() => {
  fine = true; reduced = false; frame = undefined;
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('pointer') ? fine : reduced,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  }));
  vi.stubGlobal('requestAnimationFrame', vi.fn(callback => { frame = callback; return 7; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.stubGlobal('PointerEvent', MouseEvent);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('throttles tilt to a frame, clamps angles and resets on leave without changing links', () => {
  render(<Cards />);
  const card = screen.getByRole('link');
  vi.spyOn(card, 'getBoundingClientRect').mockReturnValue({left: 0, top: 0, width: 200, height: 100} as DOMRect);
  fireEvent.pointerMove(card, {clientX: 250, clientY: -10});
  fireEvent.pointerMove(card, {clientX: 220, clientY: -5});
  expect(requestAnimationFrame).toHaveBeenCalledTimes(1);
  frame?.(0);
  expect(card.style.getPropertyValue('--tilt-x')).toBe('4deg');
  expect(card.style.getPropertyValue('--tilt-y')).toBe('4deg');
  expect(card.style.getPropertyValue('--mx')).toBe('100%');
  expect(card).toHaveAttribute('href', '#proof');
  fireEvent.pointerOut(card, {relatedTarget: document.body});
  expect(card.style.getPropertyValue('--tilt-x')).toBe('0deg');
  expect(card.style.getPropertyValue('--tilt-y')).toBe('0deg');
});
it.each(['coarse', 'reduced'])('does not enable tilt for %s input', mode => {
  if (mode === 'coarse') fine = false;
  else reduced = true;
  render(<Cards />);
  fireEvent.pointerMove(screen.getByRole('link'), {clientX: 80, clientY: 30});
  expect(requestAnimationFrame).not.toHaveBeenCalled();
  expect(screen.getByRole('link')).not.toHaveAttribute('data-tilt-ready');
});
it('cancels pending pointer work on unmount', () => {
  const view = render(<Cards />);
  fireEvent.pointerMove(screen.getByRole('link'), {clientX: 80, clientY: 30});
  view.unmount();
  expect(cancelAnimationFrame).toHaveBeenCalledWith(7);
});
