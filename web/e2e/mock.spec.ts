import {test, expect} from '@playwright/test';
import type {Page} from '@playwright/test';
import {mkdirSync} from 'node:fs';
import {homedir} from 'node:os';
import {join} from 'node:path';
import * as fx from './fixtures';

// Mocked API (no server involved): screens whose live state is not on the ward right now, and every
// state-changing button, are exercised here. Writes are captured and answered with receipts.
const OUT = process.env.SW_SHOTS || join(homedir(), 'Desktop/sentinelward/.work/screens2');
mkdirSync(OUT, {recursive: true});

async function mock(page: Page, role: string, writes: {method: string; path: string; body: unknown}[], problems: string[]) {
  page.on('console', m => { if (m.type() === 'error') problems.push(m.text()); });
  page.on('pageerror', e => problems.push(e.message));
  await page.routeWebSocket('**/ws', ws => { ws.onMessage(() => {}); });
  await page.route('**/api/**', route => {
    const r = route.request();
    const url = new URL(r.url());
    const p = url.pathname;
    const json = (body: unknown, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    if (r.method() !== 'GET') {
      if (p === '/api/session') return json({token: 'mock', role, name: `Mock ${role}`, display_name: `Mock ${role}`});
      writes.push({method: r.method(), path: p, body: r.postDataJSON()});
      return json({command_id: 'cmd_mock', accepted_at: Date.now(), request_id: 'req_mock'}, 202);
    }
    if (p === '/api/health') return json(fx.health);
    if (p === '/api/ward' || p === '/api/ward/preview') return json({received_at: Date.now(), beds: fx.beds});
    if (p === '/api/alerts') return json(fx.alerts);
    if (p === '/api/actions') return json(fx.actions);
    if (p === '/api/devices') return json(fx.devices);
    if (p.startsWith('/api/devices/')) return json(fx.network);
    if (p.endsWith('/history')) return json(fx.history);
    if (p.startsWith('/api/beds/')) return json(p.includes('B07') ? fx.bedDetail : {...fx.bedDetail, ...fx.beds.find(b => p.endsWith(b.bed_id))});
    if (p === '/api/incidents') return json([fx.incident]);
    if (p.startsWith('/api/incidents/')) return json(fx.incident);
    if (p === '/api/reports') return json([fx.report]);
    if (p === '/api/tickets') return json([]);
    return json({detail: 'not mocked'}, 404);
  });
  await page.goto('/login');
  await page.getByRole('button', {name: new RegExp({nurse: 'Central nurse', it: 'IT security', doctor: 'Doctor'}[role]!)}).click();
  await page.waitForURL(u => !u.pathname.startsWith('/login'));
}

async function shots(page: Page, name: string) {
  for (const [w, h] of [[1440, 900], [1024, 768]]) {
    await page.setViewportSize({width: w, height: h});
    await page.waitForTimeout(600);
    await page.screenshot({path: join(OUT, `${name}-${w}-mock.png`)});
  }
  await page.setViewportSize({width: 1440, height: 900});
}

test('S3 bed: BOTH verdict, bedside check and hand reading post the right bodies', async ({page}) => {
  const writes: {method: string; path: string; body: unknown}[] = [], problems: string[] = [];
  await mock(page, 'nurse', writes, problems);
  await page.goto('/bed/B07');
  await expect(page.getByText('GO NOW · possible emergency')).toBeVisible();
  await expect(page.getByText(/UNTRUSTED · last good/).first()).toBeVisible();
  await shots(page, 's03-bed');
  await page.getByRole('button', {name: 'Patient NOT OK'}).click();
  await page.getByLabel(/^HR/).fill('118');
  await page.getByRole('button', {name: 'Record hand check'}).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[0]).toMatchObject({path: '/api/beds/B07/bedside-check', body: {status: 'patient_not_ok', bedId: 'B07'}});
  expect(writes[1]).toMatchObject({path: '/api/beds/B07/manual-reading', body: {heartRate: 118}});
  expect(problems).toEqual([]);
});

test('S4 alerts: ladder sheet, ack and escalate', async ({page}) => {
  const writes: {method: string; path: string; body: unknown}[] = [], problems: string[] = [];
  await mock(page, 'nurse', writes, problems);
  await page.goto('/alerts');
  await page.locator('tbody tr').first().click();
  await expect(page.getByRole('heading', {name: 'Escalation ladder'})).toBeVisible();
  await shots(page, 's04-alerts');
  const sheet = page.locator('.sheet');
  await sheet.getByRole('button', {name: 'Escalate'}).click();
  await sheet.getByRole('button', {name: 'Acknowledge'}).click();
  await expect.poll(() => writes.map(w => w.path)).toEqual(['/api/alerts/al_b07/escalate', '/api/alerts/al_b07/ack']);
  expect(problems).toEqual([]);
});

test('S6 security: cut-off asks first, then posts isolate; undo posts undo', async ({page}) => {
  const writes: {method: string; path: string; body: unknown}[] = [], problems: string[] = [];
  await mock(page, 'it', writes, problems);
  await page.goto('/security');
  await page.getByRole('row', {name: /MON-03/}).click();
  await shots(page, 's06-security');
  await page.getByRole('button', {name: 'Cut off device'}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(writes).toEqual([]);
  await page.getByRole('button', {name: 'Yes, cut it off'}).click();
  await page.locator('.action-row', {hasText: 'cut off'}).getByRole('button', {name: 'Undo'}).click();
  await expect.poll(() => writes.map(w => w.path)).toEqual(['/api/devices/MON-03/isolate', '/api/actions/act_iso/undo']);
  expect(writes[0].body).toMatchObject({type: 'isolate_device', deviceId: 'MON-03', bedId: 'B03'});
  expect(problems).toEqual([]);
});

test('S7 incident: timeline, fingerprints, close needs a reason', async ({page}) => {
  const writes: {method: string; path: string; body: unknown}[] = [], problems: string[] = [];
  await mock(page, 'it', writes, problems);
  await page.goto('/incident/inc_7');
  await expect(page.getByText('Replay attack on MON-07, Bed B07')).toBeVisible();
  await shots(page, 's07-incident');
  await page.getByRole('button', {name: 'Close incident'}).click();
  const confirm = page.getByRole('dialog').getByRole('button', {name: 'Close incident'});
  await expect(confirm).toBeDisabled();
  await page.getByRole('dialog').locator('textarea').fill('Monitor reflashed');
  await confirm.click();
  await expect.poll(() => writes[0]).toMatchObject({path: '/api/incidents/inc_7/resolve', body: {reason: 'Monitor reflashed'}});
  expect(problems).toEqual([]);
});

test('S8 report: mark-sent stays disabled until checklist, approver and save', async ({page}) => {
  const writes: {method: string; path: string; body: unknown}[] = [], problems: string[] = [];
  await mock(page, 'it', writes, problems);
  await page.goto('/incident/inc_7/report');
  const send = page.getByRole('button', {name: 'Mark as sent by me'});
  await expect(send).toBeDisabled();
  await shots(page, 's08-report');
  await page.getByLabel(/Facts checked/).check();
  await page.getByLabel(/Evidence attached/).check();
  await page.getByLabel(/Approver/).fill('Sam (IT)');
  await expect(send).toBeDisabled(); // unsaved changes
  await page.getByRole('button', {name: 'Save draft'}).click();
  await expect(send).toBeEnabled();
  await send.click();
  await page.getByRole('button', {name: 'Yes, I sent it'}).click();
  await expect.poll(() => writes.map(w => `${w.method} ${w.path}`)).toEqual(['PATCH /api/reports/rep_7', 'POST /api/reports/rep_7/mark-sent']);
  expect(writes[0].body).toMatchObject({report: {approver: 'Sam (IT)', checklist: {facts_checked: true, evidence_reviewed: true, approved: true}}});
  expect(problems).toEqual([]);
});

test('S2 ward with alarms (mock) for the visual check', async ({page}) => {
  const problems: string[] = [];
  await mock(page, 'nurse', [], problems);
  await page.goto('/ward');
  await page.waitForTimeout(800);
  await shots(page, 's02-ward');
  expect(problems).toEqual([]);
});
