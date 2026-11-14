// Real arena, cached tag art and cameras, fed a stationary spectator fixture. Headless and muted throughout.
// NODE_PATH=<Playwright module directory> node near/web/arena-tile-focus-case.cjs
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.mjs': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.woff2': 'font/woff2', '.png': 'image/png' };
const server = http.createServer(async (req, res) => {
  const file = path.resolve(ROOT, '.' + new URL(req.url, 'http://localhost').pathname);
  if (!file.startsWith(ROOT + path.sep)) { res.writeHead(404).end(); return; }
  try { const body = await fs.readFile(file); res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream'); res.end(body); }
  catch { res.writeHead(404).end(); }
});

(async () => {
  let browser, phase = 'startup';
  try {
    const raw = JSON.parse(await fs.readFile(path.join(__dirname, 'arena/fixtures/tick-recorded.json'), 'utf8'));
    // The fixture keeps genuine fighter/item records, with no attacks, drops or motion to race the camera assertions.
    raw[5] = []; raw[6] = []; raw[7] = []; raw[8] = [];
    raw[4].forEach((f, i) => { f[1] = -5000 + (i % 5) * 2200; f[2] = -4000 + Math.floor(i / 5) * 3000; f[3] = 100; f[5] = 0; f[6] = -1; });
    raw[2].push('dev-pebble'); raw[4].push([raw[2].length - 1, 5000, 4000, 100, 0, 0, -1, 0, [...raw[4][0][8]], 0]);
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    browser = await chromium.launch({ headless: true, args: ['--mute-audio', ...(process.env.HTTPS_PROXY ? ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'] : [])],
      ...(process.env.HTTPS_PROXY ? { proxy: { server: process.env.HTTPS_PROXY } } : {}) });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.setDefaultTimeout(15000);
    const errors = [], reports = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    await page.addInitScript((snapshot) => {
      localStorage.setItem('arena-muted', '1');
      window.tileFixture = { bench: null };
      window.WebSocket = class {
        constructor() {
          this.readyState = 1;
          setTimeout(() => this.onopen?.({}), 0);
          this.timer = setInterval(() => {
            snapshot[1]++;
            for (const f of snapshot[4]) f[5] = snapshot[2][f[0]] === window.tileFixture.bench ? 1 : 0;
            this.onmessage?.({ data: JSON.stringify(snapshot) });
          }, 50);
        }
        close() { clearInterval(this.timer); this.readyState = 3; }
      };
    }, raw);
    await page.route('**/house/leaderboards.json', (route) => route.fulfill({ json: { boards: { most_correct_day: { house: [{ persona: raw[2][1], correct: 8 }, { persona: raw[2][0], correct: 3 }], players: [] } } } }));
    await page.route('**/house/roster', (route) => route.fulfill({ json: {} }));
    await page.route('**/dev/health', (route) => route.fulfill({ json: { ok: true } }));
    await page.goto('http://127.0.0.1:' + server.address().port + '/web/arena.html?fps=10&dprforce=1&shadow=256&tessellation=reduced');
    phase = 'mount all three ropes';
    await page.waitForFunction(() => window.ARENA && !ARENA.hud.mounting && ARENA.hud.cardList.length >= 3);
    const tiles = page.locator('.fighter-tile');
    assert.ok(await tiles.count() >= 8, 'baseline 5627fd0 has 0 clickable tiles; all three ropes need fighter controls');
    const checkCamera = async (tile, keyboard = false) => {
      const id = await tile.getAttribute('data-fighter-id');
      phase = (keyboard ? 'Enter ' : 'click ') + id;
      await page.evaluate(() => ArenaView.unfollow());
      assert.equal(await tile.getAttribute('role'), 'button');
      assert.equal(await tile.getAttribute('tabindex'), '0');
      assert.equal(await tile.evaluate((node) => getComputedStyle(node).cursor), 'pointer');
      if (keyboard) { await tile.focus(); await page.keyboard.press('Enter'); }
      else await tile.click();
      phase = 'follow id ' + id;
      await page.waitForFunction((id) => ArenaView.followed() === id, id);
      phase = 'camera within one tile of ' + id;
      await page.waitForFunction((id) => {
        const { inset, actors, THREE } = ARENA, p = actors.get(id)?.h.object3d.position;
        if (!p || inset.box.hidden) return false;
        const ray = inset.cam.getWorldDirection(new THREE.Vector3()), target = inset.cam.position.clone().addScaledVector(ray, (0.8 - inset.cam.position.y) / ray.y);
        return Math.hypot(target.x - p.x, target.z - p.z) < 1;
      }, id);
      reports.push({ id, activation: keyboard ? 'Enter' : 'click', cameraWithinTiles: 1 });
      return id;
    };
    const house = page.locator('[data-tile-board="KOs"] .fighter-tile');
    const predictions = page.locator('[data-tile-board="Predictions"] .fighter-tile');
    await checkCamera(house.first());
    await checkCamera(predictions.first());
    await checkCamera(page.locator('[data-tile-board="Player KOs"] .fighter-tile').first());
    await checkCamera(house.first(), true);
    // Remount with changed rankings: the same portrait control must still resolve to its own stable id.
    const mountedAt = await page.evaluate(() => { const at = ARENA.hud.lastMount; ARENA.hud.board.onKo('dev-pebble', performance.now()); ARENA.hud.sig = ''; return at; });
    await page.waitForFunction((at) => ARENA.hud.lastMount > at && !ARENA.hud.mounting, mountedAt);
    const benchId = await predictions.first().getAttribute('data-fighter-id');
    await page.evaluate((id) => { tileFixture.bench = id; ArenaView.unfollow(); }, benchId);
    await page.waitForFunction((id) => ARENA.hud.tags.get(id)?.classList.contains('bench'), benchId);
    await predictions.first().click();
    await page.waitForFunction((id) => ArenaView.waitingFor() === id, benchId);
    await page.getByRole('status').filter({ hasText: 'on the bench' }).waitFor({ state: 'visible' });
    await page.evaluate(() => { tileFixture.bench = null; });
    await page.waitForFunction((id) => ArenaView.followed() === id, benchId);
    await checkCamera(predictions.first(), true);
    assert.deepEqual(errors, [], 'arena must render without uncaught errors');
    process.stdout.write(JSON.stringify({ case: 'arena-tile-focus', reports, benchWaitAndReturn: true }) + '\n');
  } catch (error) { error.message = phase + ': ' + error.message; throw error; }
  finally { if (browser) await browser.close(); server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); }
})().catch((error) => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
