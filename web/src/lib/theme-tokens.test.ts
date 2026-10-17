import {describe,expect,it} from 'vitest';
import tokens from '../styles/tokens.css?raw';
import components from '../styles/components.css?raw';
import base from '../styles/base.css?raw';

describe('clinical colour contract',()=>{
  const light=tokens.split(':root, :root[data-theme="light"] {')[1].split(':root[data-theme="dark"]')[0];
  const dark=tokens.split(':root[data-theme="dark"] {')[1];
  it.each([
    ['emergency','#B3261E','#B83229'],['check','#F2A900','#FFB020'],
    ['security','#5B3FA8','#8F7BFF'],['maint','#B26A00','#FFB020'],
    ['ok','#2E7D32','#5BD17A'],['nodata','#8C7E79','#6E625E'],
  ])('%s uses the specified semantic colour in both themes',(name,day,night)=>{
    expect(light).toContain(`--st-${name}: ${day}`);expect(dark).toContain(`--st-${name}: ${night}`);
    expect(components).toMatch(new RegExp(`\\.state-${name}[^}]*var\\(--st-${name}\\)`));
  });
  it('uses a quieter emergency tint for badges and preserves the security edge',()=>{
    expect(components).toMatch(/\.state-emergency, \.state-both[^}]*background: var\(--st-emergency-soft\)/);
    expect(components).toMatch(/\.state-both[^}]*border-color: var\(--st-security\)/);
  });
  it.each([['light', light], ['dark', dark]])('%s emergency labels meet 4.5:1 contrast on their fills', (_name, source) => {
    const colours = Object.fromEntries([...source.matchAll(/(--[\w-]+):\s*(#[\da-f]{6})/gi)].map(m => [m[1], m[2]]));
    const luminance = (hex: string) => {
      const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
        .map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
      return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
    };
    for (const [foreground, background] of [['--st-emergency-text', '--st-emergency-soft'], ['--st-emergency-ink', '--st-emergency']]) {
      const [lo, hi] = [luminance(colours[foreground]), luminance(colours[background])].sort((a, b) => a - b);
      expect((hi + .05) / (lo + .05)).toBeGreaterThanOrEqual(4.5);
    }
  });
  it('turns off crossfade and puts the new root over the old',()=>{
    expect(base).toContain('animation: none; mix-blend-mode: normal');
    expect(base).toContain('::view-transition-new(root) { z-index: 2; }');
  });
});
