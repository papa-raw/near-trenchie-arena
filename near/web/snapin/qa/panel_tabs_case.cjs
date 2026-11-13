// Benched owners can send orders in Chat and scroll their unchanged bench controls in Gear.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/panel_tabs_case.cjs
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '../..');
const PORT = 18736;
// Markup assertions exercise the real render path without a browser. The default case also requires layout checks.
if (process.argv.includes('--markup-only')) {
  const vm = require('node:vm'), source = require('node:fs');
  const store = new Map([
    ['trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout', wallet: { accountId: 'coral.invalid' }, agreed: true, door: { route: 'key', door: 'NEAR AI Cloud' } })],
    ['trenchie.snapin.cap', '0.1']
  ]);
  const listeners = {}, saved = JSON.parse(store.get('trenchie.snapin.v1'));
  let phase = 'in', leaveCalls = 0, finishLeave, now = Date.now();
  const context = vm.createContext({
    URL, URLSearchParams, setTimeout, clearTimeout, Date: class extends Date { static now() { return now; } }, innerWidth: 390, location: { href: 'http://localhost/panel-tabs-case', search: '' },
    localStorage: { getItem: (key) => store.get(key) || null, setItem: (key, value) => store.set(key, value) },
    document: { addEventListener: (kind, fn) => { listeners[kind] = fn; }, createElement: () => ({ querySelector: () => null, contains: () => true }), body: { appendChild() {} } },
    addEventListener() {}, dispatchEvent() {}, requestAnimationFrame() {}, CustomEvent: function () {},
    SnapRoom: {
      status: () => ({ phase, fighter: phase === 'ended' ? null : { id: 'coral', name: 'Coral Scout', lives: 2 } }),
      leave: async () => { leaveCalls++; phase = 'leaving'; await new Promise((resolve) => { finishLeave = resolve; }); phase = 'ended'; }
    },
    ArenaView: { follow() {} }
  });
  for (const file of ['guide-copy.js', 'panel.js']) vm.runInContext(source.readFileSync(path.join(ROOT, 'snapin', file), 'utf8'), context);
  context.SnapPanel.state.corner = { hp: 0, max_hp: 100,
    bench: { down: true, held: true, hold: true, next_life: 2, respawn_in_ms: 34000, equipped: [], bag: [] }, events: [] };
  context.SnapPanel.render();
  const markup = context.SnapPanel.state.el.innerHTML;
  assert.match(markup, /<textarea id="pn-order"/, 'benched owner still has an order input');
  assert.match(markup, /role="tab"[^>]*aria-selected="true"[^>]*>Chat<\/button>/, 'Chat is selected by default');
  assert.match(markup, /role="tab"[^>]*>Gear/, 'Gear has its own tab');
  assert.match(markup, /data-pn="hold"/, 'bench hold control is retained');
  assert.match(markup, /data-pn="sendback"/, 'bench return control is retained');
  assert.doesNotMatch(markup, /data-pn="follow"/, 'Follow is removed');
  assert.match(markup, /class="plate leave"[^>]*data-pn="leave"[^>]*>Leave<\/button>/, 'Leave replaces Follow');
  const clickLeave = () => listeners.click({ target: { closest: () => ({ dataset: { pn: 'leave' }, tagName: 'BUTTON', disabled: false }) } });
  phase = 'joining'; context.SnapPanel.render();
  assert.match(context.SnapPanel.state.el.innerHTML, /data-pn="leave" disabled/, 'Leave is disabled while joining');
  clickLeave(); assert.equal(leaveCalls, 0, 'a stale click cannot leave during joining');
  phase = 'in'; context.SnapPanel.render(); clickLeave(); now += 600; clickLeave();
  assert.equal(leaveCalls, 1, 'Leave uses the room leave API');
  assert.equal(context.SnapPanel.state.leaving, true);
  assert.match(context.SnapPanel.state.el.innerHTML, /Coral Scout is swimming home/);
  clickLeave(); assert.equal(leaveCalls, 1, 'a pending leave cannot be sent twice');
  finishLeave();
  (async () => {
    await new Promise((resolve) => setImmediate(resolve));
    const kept = JSON.parse(store.get('trenchie.snapin.v1'));
    assert.ok(kept.left > 0); delete kept.left;
    assert.deepEqual(kept, saved, 'Leave keeps the draft, wallet and AI door');
    assert.equal(store.get('trenchie.snapin.cap'), '0.1', 'Leave keeps the cap');
    assert.equal(context.location.href, '/index.html?step=ring', 'Leave returns to the guide ring screen');
    assert.equal(context.SnapPanel.state.el.hidden, true, 'the ended fighter panel disappears');
    process.stdout.write('panel-tabs-case markup: bench input, default Chat, Gear and Leave API/guards/saved choices pass; browser layout NOT RUN\n');
  })().catch((error) => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
  return;
}
const MIME = { '.js': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png' };
const HTML = '<meta charset="utf-8"><style>body{margin:0}</style><link rel="stylesheet" href="/snapin/panel.css"><script src="/snapin/art/ska.js"></script><script src="/snapin/guide-copy.js"></script><script src="/snapin/panel.js"></script>';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/panel-tabs-case') { res.setHeader('Content-Type', 'text/html'); res.end(HTML); return; }
  // A labelled landing fixture records the requested guide destination; guide rendering belongs to its own cases.
  if (url.pathname === '/snapin/index.html' && url.searchParams.get('step') === 'ring') { res.setHeader('Content-Type', 'text/html'); res.end('<!doctype html><title>Leave destination fixture</title>'); return; }
  const file = path.resolve(ROOT, '.' + url.pathname);
  if (!file.startsWith(ROOT + path.sep)) { res.writeHead(404).end(); return; }
  try { const body = await fs.readFile(file); res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream'); res.end(body); }
  catch { res.writeHead(404).end(); }
});

async function reachable(locator) {
  assert.equal(await locator.isVisible(), true, 'control is visible');
  assert.equal(await locator.isEnabled(), true, 'control is enabled');
  assert.equal(await locator.evaluate((node) => {
    const r = node.getBoundingClientRect(), face = node.closest('.face').getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return r.width > 0 && r.height > 0 && r.x >= face.x && r.right <= face.right + 1 &&
      r.y >= face.y && r.bottom <= face.bottom + 1 && r.bottom <= innerHeight && (hit === node || node.contains(hit));
  }), true, 'control is inside the panel and can be clicked without scrolling');
}

(async () => {
  let browser;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(PORT, '127.0.0.1', resolve); });
    const options = { args: ['--single-process', '--no-zygote'] };
    if (process.env.HTTPS_PROXY) options.proxy = { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' };
    browser = await require('playwright').chromium.launch(options);
    const page = await browser.newPage(), errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto('http://127.0.0.1:' + PORT + '/panel-tabs-case');
      await page.evaluate(async () => {
        localStorage.setItem('trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout', preset: 'Brawler Swing', wallet: { accountId: 'coral.invalid' }, agreed: true, door: { route: 'key', door: 'NEAR AI Cloud' } }));
        localStorage.setItem('trenchie.snapin.cap', '0.1');
        window.orders = []; window.benchCalls = []; window.leaveCalls = 0; window.roomPhase = 'in';
        window.SnapBrain = { tell: async (order) => { orders.push(order); return { reply: 'The tide remembers.', receipt: { status: 'accepted', summary: 'New behaviour recorded: chase 8' } }; } };
        window.SnapRoom = {
          status: () => ({ phase: roomPhase, fighter: roomPhase === 'ended' ? null : { id: 'coral', name: 'Coral Scout', lives: 2 } }),
          leave: async () => { leaveCalls++; roomPhase = 'leaving'; await new Promise((resolve) => { window.finishLeave = resolve; }); roomPhase = 'ended'; },
          bench: async (payload) => {
            benchCalls.push(payload);
            const bench = SnapPanel.state.corner.bench;
            if ('hold' in payload) { bench.hold = payload.hold; bench.held = payload.hold; }
            return { ack: { summary: 'Gear ready.', bench } };
          }
        };
        window.ArenaView = { follow: () => {} };
        const state = SnapPanel.state;
        state.brain = { state: 'driving', spendHourUsd: 0.01, capUsd: 0.1 };
        state.swapMsg = 'Coral head goes on; Tide Cap goes to the bag.';
        state.corner = { hp: 0, max_hp: 100, bench: { down: true, held: false, hold: false, next_life: 2, respawn_in_ms: 34000,
          equipped: ['head', 'body', 'weapon', 'trinket'].map((slot) => ({ slot, item_id: slot, name: 'Coral ' + slot })),
          bag: Array.from({ length: 12 }, (_, i) => ({ slot: 'head', item_id: 'tide-' + i, name: 'Tide Cap ' + i })) },
          events: Array.from({ length: 20 }, (_, i) => ({ kind: 'order', at_ms: i * 1000,
            order: 'Chase the tide ' + i, reply: 'The tide returns.', receipt: { summary: 'New behaviour recorded: chase 8' } })) };
        SnapPanel.render(); await document.fonts.ready; SnapPanel.render();
      });
      const chat = page.getByRole('tab', { name: 'Chat', exact: true });
      const gear = page.getByRole('tab', { name: /^Gear/ });
      assert.equal(await chat.count(), 1, width + ': Chat tab exists');
      assert.equal(await chat.getAttribute('aria-selected'), 'true', 'Chat is the default while on the bench');
      assert.match(await gear.getAttribute('aria-label'), /gear can be changed/i, 'Gear announces that bench changes are available');
      await reachable(page.locator('#pn-order'));
      await page.locator('#pn-order').fill('Chase the tide after respawning');
      await reachable(page.locator('[data-pn="send"]'));
      await page.locator('[data-pn="send"]').click();
      await page.waitForFunction(() => orders.length === 1 && !SnapPanel.state.sending);
      assert.deepEqual(await page.evaluate(() => orders), ['Chase the tide after respawning']);
      assert.match(await page.locator('#pn-log').innerText(), /The tide remembers/);
      assert.equal(await page.locator('.benchb').isVisible(), false, 'gear never covers Chat');
      assert.equal(await page.locator('.ph [data-pn="follow"]').count(), 0);
      assert.equal(await page.locator('.mny').isVisible(), true);
      await page.locator('#pn-order').fill('Keep this draft');
      await gear.click();
      assert.equal(await gear.getAttribute('aria-selected'), 'true');
      assert.equal(await page.locator('#pn-order').isVisible(), false);
      assert.equal(await page.locator('.benchb').isVisible(), true);
      assert.equal(await page.locator('.benchb .gear .slot').count(), 4);
      assert.equal(await page.locator('.benchb .bag .slot').count(), 12);
      assert.equal(await page.locator('#pn-down').innerText(), '34');
      assert.match(await page.locator('.benchb').innerText(), /Coral head goes on; Tide Cap goes to the bag/);
      await page.locator('[data-pn="hold"]').click();
      assert.equal(await page.locator('[data-pn="hold"]').getAttribute('aria-checked'), 'true');
      await page.locator('[data-pn="equip:head:tide-11"]').click();
      assert.equal(await page.evaluate(() => {
        const pane = document.querySelector('.benchb').parentElement;
        return pane.scrollHeight > pane.clientHeight && /auto|scroll/.test(getComputedStyle(pane).overflowY) &&
          document.querySelector('.pnl').getBoundingClientRect().bottom <= innerHeight;
      }), true, 'Gear scrolls inside the panel');
      await page.locator('[data-pn="sendback"]').click();
      assert.deepEqual(await page.evaluate(() => benchCalls), [{ hold: true }, { equip: { slot: 'head', item_id: 'tide-11' } }, { hold: false }]);
      await chat.click();
      assert.equal(await page.locator('#pn-order').inputValue(), 'Keep this draft');
      await reachable(page.locator('#pn-order'));
      await page.evaluate(() => { SnapPanel.state.corner.bench.down = false; SnapPanel.render(); SnapPanel.state.corner.bench.down = true; SnapPanel.render(); });
      assert.equal(await chat.getAttribute('aria-selected'), 'true', 'going to the bench never switches away from Chat');
      await page.locator('[data-pn="close"]').click();
      await page.locator('[data-pn="open"]').click();
      assert.equal(await chat.getAttribute('aria-selected'), 'true');
      const leave = page.getByRole('button', { name: 'Leave', exact: true });
      await reachable(leave);
      assert.equal(await leave.evaluate((node) => getComputedStyle(node).color), 'rgb(194, 69, 58)', 'Leave uses the existing error red');
      await page.evaluate(() => { roomPhase = 'joining'; SnapPanel.render(); });
      assert.equal(await leave.isDisabled(), true);
      await page.evaluate(() => { roomPhase = 'in'; SnapPanel.render(); });
      const keptBefore = await page.evaluate(() => localStorage.getItem('trenchie.snapin.v1'));
      await leave.click();
      await page.waitForTimeout(600);
      await page.getByRole('button', { name: 'Leave the arena? This life ends', exact: true }).click();
      await page.waitForFunction(() => SnapPanel.state.leaving);
      assert.equal(await leave.isDisabled(), true);
      assert.match(await page.locator('.leave-msg').innerText(), /Coral Scout is swimming home/);
      assert.equal(await page.evaluate(() => leaveCalls), 1);
      await page.evaluate(() => finishLeave());
      await page.waitForURL('**/snapin/index.html?step=ring');
      const keptAfter = await page.evaluate(() => JSON.parse(localStorage.getItem('trenchie.snapin.v1')));
      assert.ok(keptAfter.left > 0); delete keptAfter.left;
      assert.deepEqual(keptAfter, JSON.parse(keptBefore), 'draft, wallet and AI door survive Leave');
      assert.equal(await page.evaluate(() => localStorage.getItem('trenchie.snapin.cap')), '0.1');
      process.stdout.write(JSON.stringify({ width, chatDefault: true, benchOrderSent: true, gearItems: 16, gearScrollable: true, benchActions: 3, draftPreserved: true, leaveRed: true, leaveCalled: true }) + '\n');
    }
    assert.deepEqual(errors, []);
    process.stdout.write('panel-tabs-case: bench orders reachable in Chat and full Gear controls at 1440/390\n');
  } finally { if (browser) await browser.close(); await new Promise((resolve) => server.close(resolve)); }
})().catch((error) => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
