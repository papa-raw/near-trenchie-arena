// Real HUD and tag CSS: crowded fighters retain separate, readable name tags and prediction circles.
// NODE_PATH=<Playwright module directory> node near/web/arena-group-tags-off-case.cjs
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..');
const MIME = { '.js': 'application/javascript', '.mjs': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2' };

(async () => {
  const arena = await fs.readFile(path.join(__dirname, 'arena.html'), 'utf8');
  const style = arena.match(/<style>[\s\S]*?<\/style>/)[0];
  const html = style + '<link rel="stylesheet" href="/web/arena/board2.css"><script type="importmap">{"imports":{"three":"/web/vendor/three/three.module.min.js"}}</script><div id="tags"></div>';
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/') { res.setHeader('Content-Type', 'text/html'); res.end(html); return; }
    const file = path.resolve(ROOT, '.' + url.pathname);
    if (!file.startsWith(ROOT + path.sep)) { res.writeHead(404).end(); return; }
    try { const body = await fs.readFile(file); res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream'); res.end(body); }
    catch { res.writeHead(404).end(); }
  });
  let browser;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(18734, '127.0.0.1', resolve); });
    browser = await chromium.launch(process.env.HTTPS_PROXY ? {
      args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY },
    } : {});
    const page = await browser.newPage(), reports = [], errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    for (const width of [1440, 390]) for (const count of [3, 5]) for (const edge of [false, true]) {
      await page.setViewportSize({ width, height: 844 }); await page.goto('http://127.0.0.1:18734/');
      const report = await page.evaluate(async ({ count, edge }) => {
        await document.fonts.load('600 11px Fredoka');
        const { Hud } = await import('/web/arena/hud.mjs');
        const names = ['Coral Clerk', 'Pebble Scout', 'Drift Clerk', 'Kelp Keeper', 'Foam Captain'];
        const ids = ['coral', 'pebble', 'dev-drift', 'kelp', 'foam'].slice(0, count);
        let kos = 1, frameNow = 0;
        const h = Object.assign(Object.create(Hud.prototype), {
          w: innerWidth, h: innerHeight, tags: new Map(), styles: new Map(), bounties: new Set(), tagPrev: new Map(),
          KITS: { roster: ids.map((id, i) => ({ trenchieId: id, tag: names[i], name: names[i] })), players: [] },
          lives: { get: () => ({ level: 2, kos }) }, tagLayer: document.getElementById('tags'), rects: {},
          toScreen: (x, y, z) => ({ x, y: z }),
        });
        const pos = (frame = 0) => new Map(ids.map((id, i) => [id, { x: (edge ? 15 : innerWidth / 2) + Math.sin(frame / 10 + i) * 2,
          z: 400 + Math.cos(frame / 10 + i) * 2, state: 'alive', f: { status: 0, items: {}, target: null } }]));
        const measure = () => [...h.tags].map(([id, node]) => { const r = node.getBoundingClientRect(), anchor = pos(frameNow).get(id); return { id, name: node.querySelector('.tname').textContent,
          visible: getComputedStyle(node).opacity !== '0' && !node.classList.contains('tag-hidden'),
          pips: node.querySelectorAll('.circ .pips i').length, met: !!node.querySelector('.pips.met'),
          leader: node.classList.contains('lead'), dev: !!node.querySelector('.dev'), ownHead: Math.abs(r.x + r.width / 2 - anchor.x) < 1 && Math.abs(r.y + r.height + 2 - anchor.z) < 1, x: r.x, y: r.y, w: r.width, h: r.height }; });
        const valid = (tags) => tags.length === count && tags.every((t) => t.visible && t.pips === 2 && t.ownHead);
        h.placeTags(pos(), 'pebble', 0);
        const first = measure(), initialValid = valid(first);
        let stable = true;
        for (let frame = 1; frame <= 30; frame++) { frameNow = frame; h.placeTags(pos(frame), 'pebble', frame * 16); stable &&= valid(measure()); }
        kos = 2; frameNow = 31; h.placeTags(pos(31), 'pebble', 496); const met = measure();
        const report = { width: innerWidth, count, edge, merged: document.querySelectorAll('.gcard').length, first, initialValid, stable,
          met: met.every((t) => t.met),
          names: first.every((t, i) => t.name === names[i]), leader: first.find((t) => t.id === 'pebble').leader, dev: first.find((t) => t.id === 'dev-drift').dev };
        h.placeTags(new Map([...pos()].map(([id, q], i) => [id, { ...q, x: 30 + i * 65, z: 600 + i * 22 }])), 'pebble', 512);
        report.separated = measure().every((t) => t.visible);
        h.placeTags(new Map(), null, 528); report.cleaned = h.tags.size === 0 && h.tagLayer.children.length === 0;
        return report;
      }, { count, edge });
      reports.push(report);
      assert.equal(report.merged, 0, width + '/' + count + ': no merged name card');
      assert.ok(report.initialValid && report.stable, 'each fighter has its own visible tag directly above its own head on every frame');
      assert.ok(report.met && report.names && report.leader && report.dev && report.separated && report.cleaned,
        'prediction circles, names, leader/DEV, separation and cleanup preserved');
    }
    assert.deepEqual(errors, []);
    process.stdout.write(JSON.stringify({ case: 'arena-group-tags-off', reports }) + '\n');
  } finally { if (browser) await browser.close(); await new Promise((resolve) => server.close(resolve)); }
})().catch((error) => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
