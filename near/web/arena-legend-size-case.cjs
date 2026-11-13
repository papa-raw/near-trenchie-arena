// Focused browser regression: the real floor-sign DOM, CSS, placement and fade, without a running fight.
// NODE_PATH=<Playwright module directory> node near/web/arena-legend-size-case.cjs
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const ROOT = __dirname;
const HTML = '<link rel="stylesheet" href="/arena/board2.css"><script type="importmap">{"imports":{"three":"/vendor/three/three.module.min.js"}}</script>';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/') { res.setHeader('Content-Type', 'text/html'); res.end(HTML); return; }
  const file = path.resolve(ROOT, '.' + url.pathname);
  if (!file.startsWith(ROOT + path.sep)) { res.writeHead(404).end(); return; }
  try {
    const body = await fs.readFile(file);
    res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : 'application/javascript'); res.end(body);
  } catch { res.writeHead(404).end(); }
});

(async () => {
  let browser;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(18734, '127.0.0.1', resolve); });
    browser = await chromium.launch(process.env.HTTPS_PROXY ? {
      args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY },
    } : {});
    const page = await browser.newPage();
    const errors = []; page.on('pageerror', (e) => errors.push(String(e)));
    const reports = [];
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('http://127.0.0.1:18734/');
      const result = await page.evaluate(async () => {
        await document.fonts.load('700 12px "Space Mono"');
        const { Hud } = await import('/arena/hud.mjs');
        const h = Object.assign(Object.create(Hud.prototype), {
          w: innerWidth, h: innerHeight, legends: new Map(), legLayer: document.body,
          rects: {}, tagRects: [], itemRenderer: null,
          ITEMS: { crown: { tier: 'legendary', name: 'Coral Crown' }, long: { tier: 'legendary', name: 'Crown of the Everlasting Coral Kingdom' } },
          toScreen: () => ({ x: innerWidth / 2, y: 450 }),
        });
        const d = { key: 'one', item: 'crown', x: 0, y: 0 };
        h.onLegendDrop(d, 1000); h.placeLegends(new Map(), 1000);
        const lg = h.legends.get('one'), sign = lg.sign, text = sign.querySelector('.legtext');
        const box = sign.getBoundingClientRect(), image = sign.firstElementChild.getBoundingClientRect(), lineHeight = text.getBoundingClientRect().height;
        const range = document.createRange(); range.selectNodeContents(text);
        const lines = [...new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.y * 10)))];
        const name = text.querySelector('.legname'), picture = sign.firstElementChild;
        const out = { width: innerWidth, scaleX: box.width / sign.offsetWidth, scaleY: box.height / sign.offsetHeight,
          picture: image.width, text: sign.textContent, title: sign.title, aria: sign.getAttribute('aria-label'),
          glow: picture.classList.contains('legend-glow') && getComputedStyle(picture).boxShadow.includes('247, 207, 107'),
          name: name?.textContent, lines: lines.length,
          measured: Math.abs(lg.w - box.width) < 1 && Math.abs(lg.h - box.height) < 1,
          clear: box.left >= 6 && box.right <= innerWidth - 6 };
        h.syncDrops([d], 3999); h.onLegendDrop(d, 3999); h.placeLegends(new Map(), 3999);
        out.beforeFade = sign.style.opacity;
        h.placeLegends(new Map(), 4150); out.midFade = sign.style.opacity;
        h.placeLegends(new Map(), 4300); out.expired = !sign.isConnected && !lg.pin.isConnected && h.legendRects.length === 0;
        h.onLegendDrop({ ...d, key: 'long', item: 'long' }, 5000); h.placeLegends(new Map(), 5000);
        const long = h.legends.get('long').sign, words = long.querySelector('.legname');
        const longBox = long.getBoundingClientRect();
        out.long = { name: words?.textContent, clear: longBox.left >= 6 && longBox.right <= innerWidth - 6,
          wraps: words ? words.getBoundingClientRect().height > lineHeight * 1.5 : false,
          noClip: words ? words.scrollWidth <= words.clientWidth + 1 && getComputedStyle(words).textOverflow !== 'ellipsis' : false };
        return out;
      });
      reports.push(result);
      assert.ok(Math.abs(result.scaleX - 0.7) < 0.01 && Math.abs(result.scaleY - 0.7) < 0.01, width + ': whole label scale must be 0.7');
      assert.ok(Math.abs(result.picture - 26 * 0.7) < 0.1, 'picture scales with the box and text');
      assert.doesNotMatch(result.text + result.title + result.aria, /legendary/i);
      assert.ok(result.glow, 'the item circle carries the calm legendary-gold halo');
      assert.equal(result.name, 'CORAL CROWN'); assert.equal(result.lines, 1);
      assert.ok(result.measured && result.clear, 'placement uses the rendered dimensions');
      assert.equal(Number(result.beforeFade), 1); assert.equal(Number(result.midFade), 0.5); assert.ok(result.expired, '3 s + 300 ms fade preserved');
      assert.equal(result.long.name, 'CROWN OF THE EVERLASTING CORAL KINGDOM');
      assert.ok(result.long.clear && result.long.noClip, 'long name stays whole and on screen');
      if (width <= 600) assert.ok(result.long.wraps, 'phone names wrap between words');
    }
    assert.deepEqual(errors, []);
    process.stdout.write(JSON.stringify({ case: 'arena-legend-size', reports }) + '\n');
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((e) => { process.stderr.write(e.stack + '\n'); process.exitCode = 1; });
