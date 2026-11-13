// Leave requires confirmation before the existing room action, on desktop and phone.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/leave_confirm_case.cjs
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '../..'), PORT = 18737;
// The virtual clock isolates the activation timing from browser scheduling.
if (process.argv.includes('--markup-only') && process.argv.includes('--rapid-only')) {
  const vm = require('node:vm'), source = require('node:fs');
  for (const gap of [0, 120, 150, 499, 500]) {
    let now = 1000, leaveCalls = 0, nextTimer = 0;
    const timers = new Map(), listeners = {};
    const context = vm.createContext({
      URL, URLSearchParams, innerWidth: 390, location: { href: 'http://localhost/', search: '' },
      Date: class extends Date { static now() { return now; } },
      setTimeout: (fn, ms) => { timers.set(++nextTimer, { fn, at: now + ms }); return nextTimer; },
      clearTimeout: (id) => timers.delete(id),
      localStorage: { getItem: () => null },
      document: { addEventListener: (kind, fn) => { listeners[kind] = fn; }, createElement: () => ({ querySelector: () => null, contains: () => true }), body: { appendChild() {} } },
      addEventListener() {}, dispatchEvent() {}, requestAnimationFrame() {}, CustomEvent: function () {},
      SnapRoom: { status: () => ({ phase: 'in', fighter: { id: 'coral', name: 'Coral Scout', lives: 1 } }),
        leave: () => { leaveCalls++; return new Promise(() => {}); } }
    });
    for (const file of ['guide-copy.js', 'panel.js']) vm.runInContext(source.readFileSync(path.join(ROOT, 'snapin', file), 'utf8'), context);
    context.SnapPanel.render();
    const click = () => listeners.click({ target: { closest: () => ({ dataset: { pn: 'leave' }, tagName: 'BUTTON', disabled: false }) } });
    click();
    const state = context.SnapPanel.state, deadline = state.leaveUntil, timer = state.leaveTimer;
    now += gap; click();
    if (gap < 500) {
      assert.equal(leaveCalls, 0, gap + ' ms repeat must not end the life');
      assert.match(state.el.innerHTML, /Leave the arena\? This life ends/, 'rapid repeat stays armed');
      assert.equal(state.leaveUntil, deadline, 'rapid repeat preserves the original deadline');
      assert.equal(state.leaveTimer, timer, 'rapid repeat preserves the original timeout');
      now = 1600; click();
    }
    assert.equal(leaveCalls, 1, 'deliberate confirmation after ' + (gap < 500 ? 600 : gap) + ' ms leaves once');
    assert.equal(timers.size, 0);
    click(); assert.equal(leaveCalls, 1, 'pending leave cannot repeat');
    process.stdout.write(JSON.stringify({ gapMs: gap, ignored: gap < 500, deliberateCalls: leaveCalls }) + '\n');
  }
  process.stdout.write('leave-confirm-case rapid markup: PASS; browser gestures NOT RUN\n');
  return;
}
if (process.argv.includes('--markup-only')) {
  const vm = require('node:vm'), source = require('node:fs');
  let now = 1000, leaveCalls = 0, phase = 'in', nextTimer = 0;
  const timers = new Map(), listeners = {}, store = new Map([
    ['trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout', door: { route: 'key', door: 'NEAR AI Cloud' } })]
  ]);
  const context = vm.createContext({
    URL, URLSearchParams, innerWidth: 390, location: { href: 'http://localhost/', search: '' },
    Date: class extends Date { static now() { return now; } },
    setTimeout: (fn, ms) => { timers.set(++nextTimer, { fn, at: now + ms }); return nextTimer; },
    clearTimeout: (id) => timers.delete(id),
    localStorage: { getItem: (key) => store.get(key) || null, setItem: (key, value) => store.set(key, value) },
    document: { addEventListener: (kind, fn) => { listeners[kind] = fn; }, createElement: () => ({ querySelector: () => null, contains: () => true }), body: { appendChild() {} } },
    addEventListener() {}, dispatchEvent() {}, requestAnimationFrame() {}, CustomEvent: function () {},
    SnapRoom: { status: () => ({ phase, fighter: { id: 'coral', name: 'Coral Scout', lives: 1 } }),
      leave: () => { leaveCalls++; return new Promise(() => {}); } }
  });
  for (const file of ['guide-copy.js', 'panel.js']) vm.runInContext(source.readFileSync(path.join(ROOT, 'snapin', file), 'utf8'), context);
  context.SnapPanel.render();
  const click = (action) => listeners.click({ target: { closest: () => action ? { dataset: { pn: action }, tagName: 'BUTTON', disabled: false } : null } });
  const asked = () => {
    assert.equal(leaveCalls, 0, 'first activation must not leave');
    assert.match(context.SnapPanel.state.el.innerHTML, /Leave the arena\? This life ends/);
  };
  const reset = () => { assert.equal(leaveCalls, 0); assert.doesNotMatch(context.SnapPanel.state.el.innerHTML, /Leave the arena\?/); };
  phase = 'joining'; click('leave'); reset(); phase = 'in';
  click('leave'); asked();
  assert.equal(timers.size, 1); now += 5001;
  for (const [id, timer] of timers) { if (timer.at <= now) { timers.delete(id); timer.fn(); } }
  reset();
  click('leave'); asked(); click(null); reset();
  click('leave'); asked(); listeners.keydown({ key: 'Escape' }); reset();
  click('leave'); asked(); now += 600; click('leave');
  assert.equal(leaveCalls, 1); assert.equal(timers.size, 0);
  click('leave'); assert.equal(leaveCalls, 1, 'pending request is not repeated');
  process.stdout.write('leave-confirm-case markup: PASS; first activation 0 calls, second 1, 5 s timeout/outside/Escape/guards; browser NOT RUN\n');
  return;
}
const HTML = '<meta charset="utf-8"><style>body{margin:0}</style><link rel="stylesheet" href="/snapin/panel.css"><script src="/snapin/art/ska.js"></script><script src="/snapin/guide-copy.js"></script><script src="/snapin/panel.js"></script><button id="outside">Arena</button>';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/') { res.setHeader('Content-Type', 'text/html'); res.end(HTML); return; }
  const file = path.resolve(ROOT, '.' + url.pathname);
  if (!file.startsWith(ROOT + path.sep)) { res.writeHead(404).end(); return; }
  try {
    const body = await fs.readFile(file);
    res.setHeader('Content-Type', ({ '.js': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png' })[path.extname(file)] || 'application/octet-stream');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
async function rapidBrowserCase(page, width) {
  const gestures = width === 390 ? ['clicks-120ms', 'touch-150ms'] : ['dblclick', 'clicks-120ms'];
  for (const gesture of gestures) {
    await page.goto('http://127.0.0.1:' + PORT + '/');
    await page.evaluate(async () => {
      localStorage.setItem('trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout' }));
      window.leaveCalls = 0;
      window.SnapRoom = { status: () => ({ phase: 'in', fighter: { id: 'coral', name: 'Coral Scout' } }),
        leave: () => { leaveCalls++; return new Promise(() => {}); } };
      SnapPanel.render(); await document.fonts.ready; SnapPanel.render();
      window.leaveTimes = [];
      document.addEventListener('click', (event) => {
        if (event.target.closest('[data-pn="leave"]')) leaveTimes.push(Date.now());
      }, true);
    });
    const leave = page.locator('[data-pn="leave"]'), box = await leave.boundingBox();
    const x = box.x + box.width / 2, y = box.y + box.height / 2;
    if (gesture === 'dblclick') await page.mouse.dblclick(x, y);
    else if (gesture === 'touch-150ms') {
      await page.touchscreen.tap(x, y); await page.waitForTimeout(150); await page.touchscreen.tap(x, y);
    } else {
      await page.mouse.click(x, y); await page.waitForTimeout(120); await page.mouse.click(x, y);
    }
    const times = await page.evaluate(() => leaveTimes);
    assert.equal(times.length, 2, gesture + ' delivered both activations');
    assert.ok(times[1] - times[0] < 500, 'repeat arrived inside the protected 500 ms');
    assert.equal(await page.evaluate(() => leaveCalls), 0, gesture + ' does not leave');
    assert.equal((await leave.innerText()).trim(), 'Leave the arena? This life ends', 'rapid repeat stays armed');
    await page.waitForTimeout(600);
    if (gesture === 'touch-150ms') await page.touchscreen.tap(x, y);
    else await page.mouse.click(x, y);
    assert.equal(await page.evaluate(() => leaveCalls), 1, 'deliberate tap confirms once');
    process.stdout.write(JSON.stringify({ width, gesture, rapidCalls: 0, deliberateCalls: 1, actualGapMs: times[1] - times[0] }) + '\n');
  }
}
(async () => {
  let browser;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(PORT, '127.0.0.1', resolve); });
    const options = { args: ['--single-process', '--no-zygote'] };
    if (process.env.HTTPS_PROXY) options.proxy = { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' };
    browser = await require('playwright').chromium.launch(options);
    const page = await browser.newPage({ hasTouch: true }), errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await rapidBrowserCase(page, width);
      if (process.argv.includes('--rapid-only')) continue;
      await page.goto('http://127.0.0.1:' + PORT + '/');
      await page.evaluate(async () => {
        localStorage.setItem('trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout', preset: 'Brawler Swing', door: { route: 'key', door: 'NEAR AI Cloud' } }));
        window.leaveCalls = 0;
        window.SnapRoom = { status: () => ({ phase: 'in', fighter: { id: 'coral', name: 'Coral Scout', lives: 1 } }),
          leave: () => { leaveCalls++; return new Promise(() => {}); } };
        SnapPanel.state.corner = { hp: 80, max_hp: 100, events: [] };
        SnapPanel.render(); await document.fonts.ready; SnapPanel.render();
      });
      const leave = page.locator('[data-pn="leave"]');
      const reset = async () => {
        assert.equal((await leave.innerText()).trim(), 'Leave');
        assert.equal(await page.evaluate(() => leaveCalls), 0);
      };
      const arm = async () => {
        const closeBefore = await page.locator('[data-pn="close"]').boundingBox();
        const leaveBefore = await leave.boundingBox();
        await leave.click();
        assert.equal(await page.evaluate(() => leaveCalls), 0, 'first tap must not end the life');
        assert.equal((await leave.innerText()).trim(), 'Leave the arena? This life ends');
        const closeAfter = await page.locator('[data-pn="close"]').boundingBox();
        assert.equal(closeAfter.x, closeBefore.x, 'close stays in the same column');
        assert.equal(closeAfter.y, closeBefore.y, 'close stays at the same height');
        assert.equal(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y).closest('[data-pn]')?.dataset.pn,
          { x: leaveBefore.x + leaveBefore.width / 2, y: leaveBefore.y + leaveBefore.height / 2 }), 'leave', 'second tap can use the first tap position');
        assert.equal(await leave.evaluate((el) => getComputedStyle(el).color), 'rgb(194, 69, 58)');
        assert.equal(await page.evaluate(() => {
          const button = document.querySelector('[data-pn="leave"]'), close = document.querySelector('[data-pn="close"]');
          const a = button.getBoundingClientRect(), b = close.getBoundingClientRect(), face = close.closest('.face').getBoundingClientRect();
          return a.right <= b.left && a.left >= face.left && b.right <= face.right && b.bottom <= innerHeight &&
            close.contains(document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2));
        }), true, 'confirmation fits and never covers the close button');
      };
      await arm();
      await page.waitForTimeout(5150);
      await reset();
      await arm();
      await page.locator('#outside').click();
      await reset();
      await arm();
      await page.getByRole('tab', { name: /^Gear/ }).click();
      await reset();
      assert.equal(await page.getByRole('tab', { name: /^Gear/ }).getAttribute('aria-selected'), 'true', 'cancelling also performs the other panel action');
      await arm();
      await page.keyboard.press('Escape');
      await reset();
      await leave.focus();
      await page.keyboard.press('Enter');
      assert.equal(await page.evaluate(() => leaveCalls), 0, 'first Enter only asks');
      await page.evaluate(() => SnapPanel.render());
      assert.equal(await leave.evaluate((el) => el === document.activeElement), true, 'render keeps keyboard confirmation focus');
      await page.waitForTimeout(600);
      await page.keyboard.press('Enter');
      assert.equal(await page.evaluate(() => leaveCalls), 1, 'second Enter uses the existing leave path');
      assert.equal(await leave.isDisabled(), true);
      assert.match(await page.locator('.leave-msg').innerText(), /Coral Scout is swimming home/);
      await page.goto('http://127.0.0.1:' + PORT + '/');
      await page.evaluate(() => {
        window.leaveCalls = 0;
        window.SnapRoom = { status: () => ({ phase: 'in', fighter: { id: 'coral', name: 'Coral Scout' } }), leave: () => { leaveCalls++; return new Promise(() => {}); } };
        SnapPanel.render();
      });
      await arm();
      await page.waitForTimeout(600);
      await leave.click();
      assert.equal(await page.evaluate(() => leaveCalls), 1, 'two taps use the existing leave path once');
      process.stdout.write(JSON.stringify({ width, firstTapCalls: 0, confirmedCalls: 1, timeout: true, outside: true, escape: true, enterTwice: true, closeReachable: true }) + '\n');
    }
    assert.deepEqual(errors, []);
    process.stdout.write('leave-confirm-case: PASS\n');
  } finally { if (browser) await browser.close(); await new Promise((resolve) => server.close(resolve)); }
})().catch((error) => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
