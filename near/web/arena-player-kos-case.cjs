// Actual HUD/frozen rope art: the player rope has its own label, and removes it with the rope.
// NODE_PATH=<Playwright module directory> node near/web/arena-player-kos-case.cjs
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const ORIGIN = 'http://127.0.0.1:18734';
const MIME = { '.js': 'application/javascript', '.mjs': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.json': 'application/json', '.png': 'image/png' };
const HTML = '<style>body{margin:0}</style><link rel="stylesheet" href="/web/arena/board2.css"><script type="importmap">{"imports":{"three":"/web/vendor/three/three.module.min.js"}}</script><script src="/web/hud-art/hud-art.js"></script><div id="root"></div>';

(async () => {
  let browser;
  try {
    browser = await chromium.launch(process.env.HTTPS_PROXY ? {
      args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY }
    } : {});
    const page = await browser.newPage(), errors = [], reports = [];
    page.on('pageerror', (e) => errors.push(e.message));
    // Serve repository bytes from memory: the fixture opens no listener or external connection.
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== ORIGIN) { await route.abort(); return; }
      if (url.pathname === '/') { await route.fulfill({ contentType: 'text/html', body: HTML }); return; }
      const file = path.resolve(ROOT, '.' + url.pathname);
      if (!file.startsWith(ROOT + path.sep)) { await route.fulfill({ status: 404, body: '' }); return; }
      try { await route.fulfill({ contentType: MIME[path.extname(file)] || 'application/octet-stream', body: await fs.readFile(file) }); }
      catch { await route.fulfill({ status: 404, body: '' }); }
    });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 }); await page.goto(ORIGIN);
      const states = await page.evaluate(async () => {
        const { Hud } = await import('/web/arena/hud.mjs'), { HudPanelCache } = await import('/web/arena/hud-cache.mjs');
        const KITS = window.KITS = { roster: [{ trenchieId: 'coral', tag: 'Coral Clerk' }], players: [{ trenchieId: 'pebble', tag: 'Pebble Scout' }] };
        const h = new Hud({ stage: { view: { w: innerWidth, h: innerHeight } }, actors: {}, KITS, ITEMS: {}, root: document.getElementById('root') });
        h.artCache = new HudPanelCache(window.HUDART, { paint: async (node) => node });
        h.correctToday = () => [{ id: 'coral', n: 2 }];
        const fighters = [{ x: -999, y: -999, tag: 'Coral Clerk', hp: 1, kos: 3, name: 'Coral Clerk' }];
        const measured = await h.artCache.mount(h.layerHost, { concept: 'candle', draft: 'a', w: innerWidth, h: innerHeight,
          fighters, topN: 3, lead: fighters[0], feed: [] }, { only: ['board', 'banner'] });
        h.artRects = Object.fromEntries(measured.rects.map((r) => [r.id, r]));
        await document.fonts.ready;
        const box = (node) => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; };
        const sameBox = (a, b) => ['x', 'y', 'w', 'h'].every((k) => Math.abs(a[k] - b[k]) < 1.1);
        const states = [];
        // Rebuild the same HUD so the last state detects a stale Player KOs label after players leave.
        for (const playerIds of [[], ['pebble'], []]) {
          await h.buildCards(playerIds, new Map([['pebble', 3]]), 3, h.artRects.board);
          const labels = [...h.cardLayer.querySelectorAll('.ropelabel')].map((el) => ({ text: el.textContent, box: box(el) }));
          const ropes = [h.layerHost.querySelector('[data-panel="board"]'), ...h.cardList.map((c) => c.node).filter(Boolean)]
            .map((el) => box(el.querySelector('svg')));
          const boxes = [...labels.map((l) => l.box), ...ropes];
          const overlaps = boxes.some((a, i) => boxes.slice(i + 1).some((b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 1.1
            && Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 1.1));
          const estimate = h.estimateCards(h.artRects.board, !!playerIds.length, true);
          states.push({ players: playerIds.length, labels, ropes, overlaps,
            reserved: boxes.every((r) => h.bannerRects.some((b) => sameBox(r, b))),
            estimateY: estimate.map((r) => r.y), actualY: h.bannerRects.map((r) => r.y),
            inView: boxes.every((r) => r.x >= 0 && r.y >= 0 && r.x + r.w <= innerWidth && r.y + r.h <= innerHeight) });
        }
        return states;
      });
      reports.push({ width, states });
    }
    console.log(JSON.stringify({ case: 'arena-player-kos', reports }));
    assert.deepEqual(errors, [], 'fixture has no browser errors');
    for (const { width, states } of reports) for (const state of states) {
      assert.deepEqual(state.labels.map((l) => l.text), state.players ? ['KOs', 'Player KOs', 'Predictions'] : ['KOs', 'Predictions'], width + ': label follows player rope presence');
      assert.equal(state.ropes.length, state.players ? 3 : 2);
      assert.ok(state.reserved && state.inView && !state.overlaps, width + ': every label and rope is reserved, visible and apart');
      assert.deepEqual(state.estimateY, state.actualY, width + ': pre-mount label height matches actual stack');
      if (state.players) {
        const label = state.labels.find((l) => l.text === 'Player KOs').box, rope = state.ropes[1];
        assert.ok(label.y + label.h <= rope.y + 1.1, width + ': Player KOs sits above the second rope');
      }
    }
    console.log('arena-player-kos: 6 states OK at 1440/390');
  } finally { if (browser) await browser.close(); }
})().catch((e) => { console.error(e.stack); process.exitCode = 1; });
