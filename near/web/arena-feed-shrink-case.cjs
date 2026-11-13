// Actual feed/CTA DOM, CSS and placement script, without a renderer or host: both bottom UI blocks scale together.
// NODE_PATH=<Playwright module directory> node near/web/arena-feed-shrink-case.cjs
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const MIME = { '.js': 'application/javascript', '.mjs': 'application/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.png': 'image/png' };
(async () => {
  const source = await fs.readFile(path.join(__dirname, 'arena.html'), 'utf8');
  const html = '<meta charset="utf-8">' + source.match(/<style>[\s\S]*?<\/style>/)[0] + '<link rel="stylesheet" href="/arena/board2.css"><div id="world" style="position:fixed;inset:0"><div class="b2" id="ui"></div></div>'
    + source.match(/<a id="snapin-cta"[\s\S]*?<\/a>\s*<script>[\s\S]*?<\/script>/)[0];
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/arena.html') { res.setHeader('Content-Type', 'text/html'); res.end(html); return; }
    const file = path.resolve(__dirname, '.' + url.pathname);
    if (!file.startsWith(__dirname + path.sep)) { res.writeHead(404).end(); return; }
    try { const body = await fs.readFile(file); res.setHeader('Content-Type', MIME[path.extname(file)] || 'application/octet-stream'); res.end(body); }
    catch { res.writeHead(404).end(); }
  });
  let browser;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(18734, '127.0.0.1', resolve); });
    browser = await chromium.launch(process.env.HTTPS_PROXY ? { args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY } } : {});
    const page = await browser.newPage(), reports = [], errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 844 }); await page.goto('http://127.0.0.1:18734/arena.html');
      const report = await page.evaluate(async () => {
        const { Feed } = await import('/arena/feed.mjs');
        const f = new Feed(document, document.getElementById('ui'), { name: () => 'Coral Clerk', colour: () => '#123456' });
        f.setNarrow(innerWidth < 600); f.box.classList.toggle('phone', innerWidth < 600); f.list.classList.add('arena-say-feed');
        f.box.style.bottom = (innerWidth < 600 ? 62 : 16) + 'px';
        f.push({ kind: 'ko', who: 'coral', victim: 'pebble' });
        f.push({ kind: 'say', who: 'coral', emoji: '🐚', text: 'Count every shell along this long shore before the next tide arrives.' });
        f.push({ kind: 'pred', who: 'coral', level: 2 });
        await document.fonts.ready; await document.querySelector('#snapin-cta img').decode();
        dispatchEvent(new Event('resize'));
        const rect = (node) => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; };
        const a = document.getElementById('snapin-cta'), cue = a.querySelector('.cue'), button = a.querySelector('.go'), image = a.querySelector('img');
        const c = rect(cue), im = rect(image), tail = a.querySelector('svg.tail'), scale = rect(a).w / a.offsetWidth;
        const old = rect(a), face = tail.dataset.face.split(',').map(Number);
        const report = { width: innerWidth, feedScale: rect(f.box).w / f.box.offsetWidth, ctaScale: scale,
          cueScale: c.w / cue.offsetWidth, buttonScale: rect(button).w / button.offsetWidth,
          imageScale: im.w / parseFloat(getComputedStyle(image).width), tailFits: Math.abs(rect(tail).w - c.w) < 1.1,
          tailFace: Math.abs(face[0] - (im.x + im.w * 0.542 - c.x) / scale) < 0.3 && Math.abs(face[1] - (im.y + im.h * 0.452 - c.y) / scale) < 0.3,
          speech: !!f.list.querySelector('li.say em'), ko: !!f.list.querySelector('li.ko'), cueText: cue.textContent, buttonText: button.textContent };
        const b = rect(f.box); report.inView = [old, b].every((r) => r.x >= 0 && r.y >= 0 && r.x + r.w <= innerWidth + 1 && r.y + r.h <= innerHeight + 1);
        report.clear = old.x + old.w <= b.x || old.x >= b.x + b.w || old.y + old.h <= b.y || old.y >= b.y + b.h;
        f.push({ kind: 'say', who: 'coral', text: 'Another shell.' }); dispatchEvent(new Event('resize'));
        const next = rect(a); report.stable = Math.abs(next.x - old.x) < 1 && Math.abs(next.y - old.y) < 1;
        return report;
      });
      reports.push(report);
      for (const key of ['feedScale', 'ctaScale', 'cueScale', 'buttonScale', 'imageScale']) assert.ok(Math.abs(report[key] - 0.8) < 0.015, width + ': ' + key + ' is 0.8');
      assert.ok(report.tailFits && report.tailFace && report.inView && report.clear && report.stable, 'tail and placement match the scaled blocks');
      assert.ok(report.speech && report.ko); assert.equal(report.cueText, 'Satrenchi:Washed ashore? I’ll walk you in.'); assert.equal(report.buttonText, 'Snap in your Trenchie');
    }
    assert.deepEqual(errors, []); process.stdout.write(JSON.stringify({ case: 'arena-feed-shrink', reports }) + '\n');
  } finally { if (browser) await browser.close(); await new Promise((resolve) => server.close(resolve)); }
})().catch((error) => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
