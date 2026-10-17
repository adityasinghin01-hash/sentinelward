import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {ConfirmDialog, StateChip, stateChips, Toaster} from './ui';
import {ThemeToggle} from './ThemeToggle';
import {applyTheme, initializeTheme} from '../lib/theme';
import {MemoryRouter} from 'react-router-dom';
import {App} from '../App';
import {useWard} from '../lib/store';

beforeEach(() => {
  const storage = () => {const map=new Map<string,string>(); return {getItem:(k:string)=>map.get(k)??null,setItem:(k:string,v:string)=>{map.set(k,String(v))},removeItem:(k:string)=>{map.delete(k)},clear:()=>map.clear()}};
  vi.stubGlobal('localStorage', storage());
  vi.stubGlobal('sessionStorage', storage());
  localStorage.clear();
  vi.stubGlobal('matchMedia', vi.fn(() => ({matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn()})));
  applyTheme('light');
});
afterEach(() => {cleanup(); vi.unstubAllGlobals();});

describe('clinical chips', () => {
  const expected = {
    NORMAL: ['NORMAL', 'ok'], EMERGENCY: ['EMERGENCY', 'emergency'],
    BOTH: ['EMERGENCY · ATTACK SUSPECTED', 'both'], TAMPERING: ['POSSIBLE TAMPERING', 'security'],
    DEVICE_ATTACK: ['DEVICE ATTACK SUSPECTED', 'security'], UNSURE: ['CHECK BY HAND', 'check'],
    DRIFTING: ['SENSOR DRIFT', 'maint'], LOOSE_SENSOR: ['LOOSE SENSOR', 'maint'], NO_DATA: ['NO DATA', 'nodata'],
  };
  it.each(Object.entries(expected))('%s has a word, icon and semantic state colour', (state, [word, tone]) => {
    const {container} = render(<StateChip state={state as keyof typeof stateChips}/>);
    expect(screen.getByText(word)).toBeInTheDocument();
    expect(container.firstChild).toHaveClass(`state-${tone}`);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });
});
it('theme toggle applies and persists the instant reduced-motion path', () => {
  const transition = vi.fn();
  Object.defineProperty(document, 'startViewTransition', {configurable:true, value: transition});
  render(<ThemeToggle/>);
  fireEvent.click(screen.getByRole('button', {name: /Switch to dark/}));
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  expect(localStorage.getItem('sw.theme')).toBe('dark');
  expect(transition).not.toHaveBeenCalled();
  delete (document as unknown as {startViewTransition?: unknown}).startViewTransition;
});
it('uses route defaults unless a preference was saved', () => {
  initializeTheme('/ward'); expect(document.documentElement.dataset.theme).toBe('dark');
  initializeTheme('/login'); expect(document.documentElement.dataset.theme).toBe('light');
  localStorage.setItem('sw.theme','dark'); initializeTheme('/');
  expect(document.documentElement.dataset.theme).toBe('dark');
});
it('starts a named confirmation on Cancel', async () => {
  render(<ConfirmDialog open title="Isolate monitor?" bed="B03" monitor="MON-03" consequence="Incoming signals stop. Check by hand." onClose={()=>{}} onConfirm={()=>{}}/>);
  expect(screen.getByRole('alertdialog')).toHaveTextContent('B03');
  expect(screen.getByRole('alertdialog')).toHaveTextContent('MON-03');
  await waitFor(()=>expect(screen.getByRole('button',{name:'Cancel'})).toHaveFocus());
  expect(screen.getByRole('button',{name:'Isolate monitor'})).toHaveClass('button-danger');
});
it('logout clears the session, reaches login and shows Signed out', async () => {
  useWard.setState({session:{token:'t', role:'nurse',name:'priya',display_name:'Priya'},beds:[],alerts:[],actions:[]});
  vi.stubGlobal('WebSocket', class {close(){} });
  vi.stubGlobal('fetch',vi.fn(async (url:string,init?:RequestInit)=>new Response(JSON.stringify(init?.method==='DELETE'?{}:url.startsWith('/api/ward')?{beds:[],received_at:1}:url.startsWith('/api/actions')?{actions:[]}:[]))));
  render(<MemoryRouter initialEntries={['/ward']}><App/></MemoryRouter>);
  fireEvent.keyDown(await screen.findByRole('button',{name:/Account/}),{key:'Enter'});
  fireEvent.click(await screen.findByRole('menuitem',{name:/Log out/}));
  await waitFor(()=>expect(useWard.getState().session).toBeNull());
  expect(await screen.findByText('Signed out')).toBeInTheDocument();
  expect(await screen.findByRole('heading',{name:'Sign in to SentinelWard'})).toBeInTheDocument();
});

it('serializes the circular unveil and animates the new root for 260 ms', async () => {
  vi.stubGlobal('matchMedia',()=>({matches:false}));
  let finish!:()=>void;
  const finished=new Promise<void>(resolve=>{finish=resolve});
  const animate=vi.fn();
  Object.defineProperty(document.documentElement,'animate',{configurable:true,value:animate});
  const start=vi.fn((update:()=>void)=>{update();return {ready:Promise.resolve(),finished}});
  Object.defineProperty(document,'startViewTransition',{configurable:true,value:start});
  render(<ThemeToggle scope="app"/>);
  fireEvent.click(screen.getByRole('button',{name:/Switch to dark/}));
  fireEvent.click(screen.getByRole('button',{name:/Switch to light/}));
  expect(start).toHaveBeenCalledTimes(1);
  await waitFor(()=>expect(animate).toHaveBeenCalledWith(expect.objectContaining({clipPath:expect.any(Array)}),expect.objectContaining({duration:260,pseudoElement:'::view-transition-new(root)',easing:'cubic-bezier(.22,1,.36,1)'})));
  finish(); await finished; await Promise.resolve();
  fireEvent.click(screen.getByRole('button',{name:/Switch to light/}));
  expect(start).toHaveBeenCalledTimes(2);
  await Promise.resolve();
  delete (document as unknown as {startViewTransition?:unknown}).startViewTransition;
});
it('keeps theme switching usable when storage is blocked', () => {
  vi.stubGlobal('localStorage',{getItem:()=>{throw Error('blocked')},setItem:()=>{throw Error('blocked')}});
  initializeTheme('/ward'); expect(document.documentElement.dataset.theme).toBe('dark');
  render(<ThemeToggle/>); fireEvent.click(screen.getByRole('button',{name:/Switch to light/}));
  expect(document.documentElement.dataset.theme).toBe('light');
});
