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
  it('gives BOTH the emergency fill and a security edge',()=>{
    expect(components).toMatch(/\.state-emergency, \.state-both[^}]*background: var\(--st-emergency\)/);
    expect(components).toMatch(/\.state-both[^}]*border-color: var\(--st-security\)/);
  });
  it('turns off crossfade and puts the new root over the old',()=>{
    expect(base).toContain('animation: none; mix-blend-mode: normal');
    expect(base).toContain('::view-transition-new(root) { z-index: 2; }');
  });
});
