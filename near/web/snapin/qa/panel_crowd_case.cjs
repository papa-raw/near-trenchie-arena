// Real player panel: the equipped grid and a long eight-reflex plan stack without overlap; the plan scrolls locally.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/panel_crowd_case.cjs
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '../..');
const MIME = { '.js': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png' };
const HTML = '<meta charset="utf-8"><style>body{margin:0}</style><link rel="stylesheet" href="/snapin/panel.css"><script src="/snapin/guide-copy.js"></script><script src="/snapin/panel.js"></script>';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/panel-case') { res.setHeader('Content-Type', 'text/html'); res.end(HTML); return; }
  const file = path.resolve(ROOT, '.' + url.pathname);
  if (!file.startsWith(ROOT + path.sep)) { res.writeHead(404).end(); return; }
  try { const body = await fs.readFile(file); res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream'); res.end(body); }
  catch { res.writeHead(404).end(); }
});
(async () => {
  let browser;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(18734, '127.0.0.1', resolve); });
    browser = await chromium.launch(process.env.HTTPS_PROXY ? { args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY } } : {});
    const page = await browser.newPage(), reports = [], errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 }); await page.goto('http://127.0.0.1:18734/panel-case');
      const report = await page.evaluate(async () => {
        localStorage.setItem('trenchie.snapin.v1', JSON.stringify({ name: 'Coral Scout', preset: 'Brawler Swing', door: { route: 'key', door: 'NEAR AI Cloud' } }));
        localStorage.setItem('trenchie.snapin.cap', '0.1');
        window.SnapRoom = { status: () => ({ phase: 'in', fighter: { id: 'coral', name: 'Coral Scout', lives: 2 } }) };
        const state = SnapPanel.state;
        const reflexes = Array.from({ length: 8 }, (_, i) => 'reflex ' + (i + 1) + ': if target hp below 30% then stance berserk and say “The tide returns, so keep chasing until the shore is quiet.”');
        state.corner = { hp: 0, max_hp: 100, bench: { down: true, held: false, hold: false, next_life: 2, respawn_in_ms: 34000,
          equipped: ['head', 'body', 'weapon', 'trinket'].map((slot) => ({ slot, item_id: slot, name: 'Coral ' + slot })), bag: [] },
          events: [{ kind: 'order', at_ms: 1000, receipt: { summary: ['chase 8', 'attack gate: hp below 80%', 'target coral-scout', ...reflexes].join(' · ') } }] };
        SnapPanel.render(); await document.fonts.ready; SnapPanel.render();
        const panel = document.querySelector('.pnl'), face = panel.querySelector('.face'), bench = panel.querySelector('.benchb'), gear = bench.querySelector('.gear'), plan = panel.querySelector('.slip'), log = panel.querySelector('#pn-log');
        const rect = (node) => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, bottom: r.bottom, right: r.right }; };
        const p = rect(panel), f = rect(face), b = rect(bench), g = rect(gear), box = rect(plan), l = rect(log);
        plan.scrollTop = plan.scrollHeight;
        const text = plan.querySelector('li:last-child').firstChild, end = document.createRange();
        end.setStart(text, text.length - 1); end.setEnd(text, text.length);
        const last = rect(end);
        return { width: innerWidth, panel: p, face: f, bench: b, gear: g, plan: box, log: l,
          gearCount: gear.children.length, lines: plan.querySelectorAll('li').length,
          visible: box.w > 0 && box.h > 40, noOverlap: box.y >= g.bottom + 4 && l.y >= b.bottom - 0.5 && g.bottom <= b.bottom + 0.5,
          contained: box.x >= f.x && box.right <= f.right + 1 && box.y >= f.y && box.bottom <= f.bottom + 1,
          scrollable: /auto|scroll/.test(getComputedStyle(plan).overflowY) && plan.scrollHeight > plan.clientHeight,
          lastVisible: last.y >= box.y - 1 && last.bottom <= box.bottom + 1,
          copy: plan.textContent.includes('reflex 8:') };
      });
      reports.push(report); process.stdout.write(JSON.stringify(report) + '\n');
      assert.ok(report.visible && report.noOverlap && report.contained, width + ': bench grid and plan are stacked inside panel');
      assert.ok(report.scrollable && report.lastVisible, 'the plan scrolls inside its own box to its final line');
      assert.equal(report.gearCount, 4); assert.equal(report.lines, 11); assert.ok(report.copy);
    }
    assert.deepEqual(errors, []); process.stdout.write('panel-crowd-case: long plan and four-item bench fit at 1440/390\n');
  } finally { if (browser) await browser.close(); await new Promise((resolve) => server.close(resolve)); }
})().catch((error) => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
