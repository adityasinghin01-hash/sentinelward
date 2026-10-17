import {act, cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {MemoryRouter} from 'react-router-dom';
import {RoleViews} from './RoleViews';
import {SafetyPrinciples} from './SafetyPrinciples';
import {SignalChips} from './SignalChips';
import {SiteFooter} from './SiteFooter';

// The web tsconfig intentionally has no Node types; Vitest provides the built-in.
const {existsSync, readFileSync} = await vi.importActual<{
  existsSync: (path: string) => boolean;
  readFileSync: (path: string, encoding: 'utf8') => string;
}>('node:fs');
const {resolve} = await vi.importActual<{resolve: (...paths: string[]) => string}>('node:path');
const repoFile = (path: string) => resolve('..', path);

let reduced = false;
let intersect: (visible: boolean) => void;
let motionChange: (() => void) | undefined;
beforeEach(() => {
  reduced = false;
  vi.useFakeTimers();
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    get matches() { return query.includes('reduced-motion') ? reduced : false; }, media: query,
    addEventListener: (_: string, callback: () => void) => { if (query.includes('reduced-motion')) motionChange = callback; },
    removeEventListener: vi.fn(),
  })));
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: IntersectionObserverCallback) {
      intersect = visible => callback([{isIntersecting: visible} as IntersectionObserverEntry], this as unknown as IntersectionObserver);
    }
    observe() {} disconnect() {} unobserve() {}
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); motionChange = undefined; });
const cards = () => screen.getAllByRole('button');
const selected = () => cards().findIndex(card => card.getAttribute('aria-pressed') === 'true');

describe('one incident, five role views', () => {
  it('renders five roles and the verified run N timeline', () => {
    render(<RoleViews />);
    expect(cards()).toHaveLength(5);
    ['Nurse', 'Doctor', 'IT security', 'Biomed', 'Operator'].forEach(role => expect(screen.getByRole('button', {name: role})).toBeInTheDocument());
    ['13:49', '13:54', '14:04', '14:05'].forEach(time => expect(screen.getByText(time)).toBeInTheDocument());
    expect(screen.getByText(/Night ward run N, build 4348467/)).toBeInTheDocument();
    expect(screen.getByText(/no automatic repair ticket/i)).toBeInTheDocument();
  });
  it('cycles only onscreen and stops on hover, then resumes on leave', () => {
    render(<RoleViews />);
    expect(vi.getTimerCount()).toBe(0);
    act(() => intersect(true));
    act(() => vi.advanceTimersByTime(2800));
    expect(selected()).toBe(1);
    fireEvent.mouseEnter(cards()[3]);
    expect(selected()).toBe(3);
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(8400));
    expect(selected()).toBe(3);
    fireEvent.mouseLeave(cards()[3]);
    act(() => vi.advanceTimersByTime(2800));
    expect(selected()).toBe(4);
    act(() => intersect(false));
    expect(vi.getTimerCount()).toBe(0);
  });
  it('pauses on keyboard focus and does not resume while focus remains inside', () => {
    render(<RoleViews />);
    act(() => intersect(true));
    fireEvent.focus(cards()[2]);
    fireEvent.mouseEnter(cards()[2]);
    fireEvent.mouseLeave(screen.getByRole('group', {name: 'B07 role views'}));
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(5600));
    expect(selected()).toBe(2);
    fireEvent.blur(cards()[2], {relatedTarget: document.body});
    expect(vi.getTimerCount()).toBe(1);
  });
  it('clears the interval when hidden and on unmount', () => {
    const view = render(<RoleViews />);
    act(() => intersect(true));
    expect(vi.getTimerCount()).toBe(1);
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    fireEvent(document, new Event('visibilitychange'));
    expect(vi.getTimerCount()).toBe(0);
    hidden.mockReturnValue(false);
    fireEvent(document, new Event('visibilitychange'));
    expect(vi.getTimerCount()).toBe(1);
    hidden.mockRestore();
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('shows all five equally with no interval under reduced motion', () => {
    reduced = true;
    render(<RoleViews />);
    act(() => intersect(true));
    expect(vi.getTimerCount()).toBe(0);
    expect(selected()).toBe(-1);
    fireEvent.mouseEnter(cards()[1]);
    expect(selected()).toBe(-1);
    expect(screen.getByRole('region', {name: 'One event. Five role views.'})).toHaveAttribute('data-static', 'true');
  });
  it('responds when reduced motion changes during a visit', () => {
    render(<RoleViews />);
    act(() => intersect(true));
    expect(vi.getTimerCount()).toBe(1);
    act(() => { reduced = true; motionChange?.(); });
    expect(vi.getTimerCount()).toBe(0);
    expect(selected()).toBe(-1);
  });
});

it('renders four safety principles, each with an existing source', () => {
  render(<SafetyPrinciples />);
  const principles = screen.getAllByRole('article');
  expect(principles).toHaveLength(4);
  principles.forEach(card => {
    expect(within(card).getByText(/source:/i)).toBeInTheDocument();
    within(card).getAllByRole('link').forEach(link => {
      const path = link.getAttribute('href')!.split('/blob/main/')[1];
      expect(existsSync(repoFile(path)), path).toBe(true);
    });
  });
});

it('keeps all signal chips decorative and pauses them offscreen or when hidden', () => {
  const {container} = render(<div className="l-hero"><SignalChips /></div>);
  const chips = container.querySelector('.l-signal-chips')!;
  expect(chips).toHaveAttribute('aria-hidden', 'true');
  expect(chips.children.length).toBeGreaterThanOrEqual(4);
  act(() => intersect(false));
  expect(chips).toHaveAttribute('data-paused');
  act(() => intersect(true));
  expect(chips).not.toHaveAttribute('data-paused');
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  fireEvent(document, new Event('visibilitychange'));
  expect(chips).toHaveAttribute('data-paused');
  hidden.mockRestore();
});

it('links all five existing evidence files, the exploration guide, repository and credited sources', () => {
  render(<MemoryRouter><SiteFooter /></MemoryRouter>);
  const repo = 'https://github.com/adityasinghin01-hash/sentinelward';
  ['WARD-RUN', 'ML-RESULTS', 'SECURITY', 'SCALE', 'CONTAINERS'].forEach(name => {
    const path = `docs/evidence/${name}.md`;
    expect(screen.getByRole('link', {name})).toHaveAttribute('href', `${repo}/blob/main/${path}`);
    expect(existsSync(repoFile(path)), path).toBe(true);
  });
  expect(screen.getByRole('link', {name: 'GitHub repository'})).toHaveAttribute('href', repo);
  expect(screen.getByRole('link', {name: 'Live ward'})).toHaveAttribute('href', '/login?role=nurse');
  expect(screen.getByRole('link', {name: 'Explore everything yourself'})).toHaveAttribute('href', `${repo}/blob/main/docs/EXPLORE.md`);
  expect(existsSync(repoFile('docs/EXPLORE.md'))).toBe(true);
  const credits = screen.getByRole('navigation', {name: 'Open source'});
  const readme = readFileSync(repoFile('README.md'), 'utf8');
  within(credits).getAllByRole('link').forEach(link => expect(readme).toContain(`(${link.getAttribute('href')})`));
});
