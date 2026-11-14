// Actual HUD and frozen SVG art: every part of the KOs/predictions stack shrinks together, with matching reservations.
// NODE_PATH=<Playwright module directory> node near/web/arena-banner-shrink-case.cjs
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const MIME = { '.js': 'application/javascript', '.mjs': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.json': 'application/json', '.png': 'image/png' };
const HTML = '<style>body{margin:0}</style><link rel="stylesheet" href="/web/arena/board2.css"><script type="importmap">{"imports":{"three":"/web/vendor/three/three.module.min.js"}}</script><script src="/web/hud-art/hud-art.js"></script><div id="root"></div>';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/') { res.setHeader('Content-Type', 'text/html'); res.end(HTML); return; }
  const file = path.resolve(ROOT, '.' + url.pathname);
  if (!file.startsWith(ROOT + path.sep)) { res.writeHead(404).end(); return; }
  try { const body = await fs.readFile(file); res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream'); res.end(body); }
  catch { res.writeHead(404).end(); }
});
(async () => {
  let browser;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(18734, '127.0.0.1', resolve); });
    browser = await chromium.launch(process.env.HTTPS_PROXY ? {
      args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY },
    } : {});
    const page = await browser.newPage(), reports = [];
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 }); await page.goto('http://127.0.0.1:18734/');
      const report = await page.evaluate(async () => {
        const { Hud } = await import('/web/arena/hud.mjs'), { HudPanelCache } = await import('/web/arena/hud-cache.mjs');
        const KITS = window.KITS = { roster: [{ trenchieId: 'coral', tag: 'Coral Clerk' }], players: [{ trenchieId: 'pebble', tag: 'Pebble Scout' }] };
        const h = new Hud({ stage: { view: { w: innerWidth, h: innerHeight } }, actors: {}, KITS, ITEMS: {}, root: document.getElementById('root') });
        h.artCache = new HudPanelCache(window.HUDART, { paint: async (node) => node });
        h.correctToday = () => [{ id: 'coral', n: 2 }];
        const fighters = [{ x: -999, y: -999, tag: 'Coral Clerk', hp: 1, kos: 3, name: 'Coral Clerk' }];
        const o = { concept: 'candle', draft: 'a', w: innerWidth, h: innerHeight, fighters, topN: 3, lead: fighters[0], feed: [] };
        const measured = await h.artCache.mount(h.layerHost, o, { only: ['board', 'banner'] });
        h.artRects = Object.fromEntries(measured.rects.map((r) => [r.id, r]));
        await h.buildCards(['pebble'], new Map([['pebble', 3]]), 3, h.artRects.board);
        await document.fonts.ready;
        const rect = (node) => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; };
        const house = h.layerHost.querySelector('[data-panel="board"]'), houseBox = rect(house.querySelector('svg'));
        const labels = [...h.cardLayer.querySelectorAll('.ropelabel')].map((node) => ({ text: node.textContent, scale: rect(node).w / node.offsetWidth, box: rect(node) }));
        const boards = [house, ...h.cardList.map((c) => c.node).filter(Boolean)].map((node) => rect(node.querySelector('svg')));
        const boxes = [...labels.map((l) => l.box), ...boards];
        const matches = boxes.every((r) => h.bannerRects.some((b) => ['x', 'y', 'w', 'h'].every((k) => Math.abs(r[k] - b[k]) < 1.1)));
        const overlaps = boxes.some((a, i) => boxes.slice(i + 1).some((b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 1.1 && Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 1.1));
        return { width: innerWidth, houseScale: houseBox.w / h.artRects.board.w, labels, boards,
          matches, overlaps, reservations: h.bannerRects, inView: boxes.every((r) => r.x >= 0 && r.y >= 0 && r.x + r.w <= innerWidth && r.y + r.h <= innerHeight),
          estimateScale: h.estimateCards(h.artRects.board, true, true)[1].w / h.artRects.board.w };
      });
      reports.push(report);
      assert.ok(Math.abs(report.houseScale - 0.64) < 0.005, width + ': the existing 0.8 rope scale shrinks by a further 0.8');
      assert.deepEqual(report.labels.map((l) => l.text), ['KOs', 'Player KOs', 'Predictions']);
      assert.ok(report.labels.every((l) => Math.abs(l.scale - 0.8) < 0.015), 'wood labels scale with ropes, portraits and counters');
      assert.equal(report.boards.length, 3, 'house, player and prediction ropes remain');
      assert.ok(report.matches && report.inView && !report.overlaps, 'scaled reservations match drawn panels, on screen and apart');
      assert.ok(Math.abs(report.estimateScale - 0.64) < 0.005, 'pre-mount reservation also shrinks');
    }
    process.stdout.write(JSON.stringify({ case: 'arena-banner-shrink', reports }) + '\n');
  } finally { if (browser) await browser.close(); await new Promise((resolve) => server.close(resolve)); }
})().catch((e) => { process.stderr.write(e.stack + '\n'); process.exitCode = 1; });
