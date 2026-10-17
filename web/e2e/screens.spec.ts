import {test, expect} from '@playwright/test';
import type {Page} from '@playwright/test';
import {mkdirSync} from 'node:fs';
import {homedir} from 'node:os';
import {join} from 'node:path';

// Live screenshots of every screen through the dev-server proxy. READ-ONLY on the server:
// every non-GET request except the one-click login (POST /api/session) is blocked and fails the test.
const OUT = process.env.SW_SHOTS || join(homedir(), 'Desktop/sentinelward/.work/screens2');
mkdirSync(OUT, {recursive: true});
const SIZES = [{w: 1440, h: 900}, {w: 1024, h: 768}];
const ROLE_LABEL = {nurse: 'Central nurse', doctor: 'Doctor / tele-ICU', it: 'IT security', biomedical: 'Biomedical engineer', operator: 'Demo operator'} as const;
type Role = keyof typeof ROLE_LABEL;

// The only tolerated console line is Chrome's own network log for GET /api/briefing answering 503,
// which API.md documents as "no briefing published yet"; the screen shows an empty state for it.
function guard(page: Page, problems: string[], allow503 = false) {
  page.on('console', m => {
    if (m.type() !== 'error') return;
    if (allow503 && /status of 503/.test(m.text())) return;
    problems.push(`console: ${m.text()}`);
  });
  page.on('response', r => { if (r.status() >= 400 && !(allow503 && r.status() === 503 && r.url().includes('/api/briefing'))) problems.push(`http ${r.status()}: ${r.url()}`); });
  page.on('pageerror', e => problems.push(`pageerror: ${e.message}`));
  void page.route('**/api/**', route => {
    const r = route.request();
    if (r.method() === 'GET' || (r.method() === 'POST' && new URL(r.url()).pathname === '/api/session')) return route.continue();
    problems.push(`blocked write: ${r.method()} ${r.url()}`);
    return route.abort();
  });
}

async function login(page: Page, role: Role) {
  await page.goto('/login');
  await page.getByRole('button', {name: new RegExp(ROLE_LABEL[role])}).click();
  await page.waitForURL(u => !u.pathname.startsWith('/login'));
}

async function shot(page: Page, name: string, path: string, size: {w: number; h: number}, settle?: (p: Page) => Promise<void>) {
  await page.setViewportSize({width: size.w, height: size.h});
  await page.goto(path);
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(2500);
  if (settle) await settle(page);
  await page.screenshot({path: join(OUT, `${name}-${size.w}.png`)});
}

// Pick the most interesting live targets so screenshots show real states, not just calm beds.
async function targets(page: Page) {
  return page.evaluate(async () => {
    const token = JSON.parse(sessionStorage.getItem('sw.session') || 'null')?.token;
    const get = (p: string) => fetch(p, {headers: {Authorization: `Bearer ${token}`}}).then(r => (r.ok ? r.json() : null));
    const ward = await get('/api/ward');
    const rank = {high: 0, medium: 1, low: 2, none: 3} as Record<string, number>;
    const beds = (ward?.beds ?? []).slice().sort((a: {priority: string; is_trusted: boolean}, b: {priority: string; is_trusted: boolean}) =>
      rank[a.priority] - rank[b.priority] || Number(a.is_trusted) - Number(b.is_trusted));
    const incidents = (await get('/api/incidents')) ?? [];
    return {bed: beds[0]?.bed_id ?? 'B01', incident: incidents[0]?.record_id ?? null as string | null};
  });
}

const PLAN: {name: string; role: Role | null; path: (t: {bed: string; incident: string | null}) => string; settle?: (p: Page) => Promise<void>}[] = [
  {name: 's00-landing', role: null, path: () => '/'},
  {name: 's01-login', role: null, path: () => '/login'},
  {name: 's02-ward', role: 'nurse', path: () => '/ward'},
  {name: 's03-bed', role: 'nurse', path: t => `/bed/${t.bed}`},
  {name: 's04-alerts', role: 'nurse', path: () => '/alerts', settle: async p => { const row = p.locator('tbody tr').first(); if (await row.count()) await row.click(); await p.waitForTimeout(300); }},
  {name: 's05-census', role: 'doctor', path: () => '/census'},
  {name: 's06-security', role: 'it', path: () => '/security'},
  {name: 's07-incident', role: 'it', path: t => (t.incident ? `/incident/${t.incident}` : '/incident')},
  {name: 's08-report', role: 'it', path: t => `/incident/${t.incident ?? 'none'}/report`},
  {name: 's09-tickets', role: 'biomedical', path: () => '/tickets'},
  {name: 's10-briefing', role: 'nurse', path: () => '/briefing'},
  {name: 's10-workload', role: 'nurse', path: () => '/briefing', settle: async p => { await p.getByRole('button', {name: 'Workload'}).click(); await p.waitForTimeout(1500); }},
  {name: 's11-log', role: 'it', path: () => '/log'},
  {name: 's12-demo', role: 'operator', path: () => '/demo'},
];

for (const item of PLAN) {
  test(`${item.name} (live)`, async ({page}) => {
    const problems: string[] = [];
    guard(page, problems, item.name.startsWith('s10'));
    if (item.role) await login(page, item.role);
    const t = item.role ? await targets(page) : {bed: 'B01', incident: null};
    for (const size of SIZES) await shot(page, item.name, item.path(t), size, item.settle);
    // Ignore only the browser's own log line for an intentionally blocked write (none expected).
    expect(problems, problems.join('\n')).toEqual([]);
    await expect(page.locator('body')).not.toBeEmpty();
  });
}
