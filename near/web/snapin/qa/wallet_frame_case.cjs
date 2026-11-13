// Wallet-step wood geometry and the initial document while the module bridge is delayed.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/wallet_frame_case.cjs
'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
const HOSTS = require('./hosts.cjs');
const REPO = path.resolve(__dirname, '../../../..');
(async () => {
  let browser;
  const failures = [];
  try {
    const web = await HOSTS.start(['near/web/snapin/serve.py', '--port', '18734', '--arena', 'http://127.0.0.1:9'], o => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1], REPO);
    const base = 'http://127.0.0.1:' + web.m, url = base + '/web/snapin/index.html?step=wallet';
    browser = await chromium.launch(process.env.HTTPS_PROXY ? { args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY } } : {});
    const context = await browser.newContext();
    for (const width of [1440, 390]) {
      await context.route(u => !['127.0.0.1', 'localhost'].includes(u.hostname), r => r.abort());
      await context.route(base + '/dev/health', r => r.fulfill({ json: { chain_mode: { identity_network: 'mainnet', identity_nft: 'nft.trenchie-arena.near' } } }));
      const page = await context.newPage();
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      // A cold document must paint useful island UI before its module graph or fonts arrive.
      await page.route('**/art/bridge.js', r => r.abort());
      await page.goto(url);
      const initial = await page.evaluate(() => {
        const status = document.querySelector('#app [role="status"]');
        return { url: location.href, title: document.title, status: status?.textContent.trim(),
          background: getComputedStyle(document.body).backgroundColor,
          styled: !!status && getComputedStyle(status).padding !== '0px' && getComputedStyle(status).backgroundColor !== 'rgba(0, 0, 0, 0)' };
      });
      console.log(JSON.stringify({ width, initial }));
      if (!initial.styled || !initial.status) failures.push(width + ': initial wallet document has no styled status');
      await page.unroute('**/art/bridge.js'); await page.reload();
      await page.waitForFunction(() => window.__SNAPIN_READY, null, { timeout: 30000 });
      await page.waitForFunction(() => getComputedStyle(document.querySelector('.sign')).position === 'absolute');
      await page.evaluate(() => document.fonts.ready);
      const boxes = await page.evaluate(() => {
        const sign = document.querySelector('.sign'), face = sign.querySelector('.face'), svg = sign.querySelector(':scope > svg.material');
        const rect = el => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom }; };
        const matrix = svg.getScreenCTM(), vb = svg.viewBox.baseVal;
        const a = new DOMPoint(0, 0).matrixTransform(matrix), b = new DOMPoint(vb.width, vb.height).matrixTransform(matrix);
        return { frame: { x: a.x, y: a.y, right: b.x, bottom: b.y }, sign: rect(sign), panel: rect(face), body: rect(face.querySelector('.face-body')), footer: rect(face.querySelector('.bar')) };
      });
      console.log(JSON.stringify({ width, ...boxes }));
      const { frame: f, panel: p } = boxes;
      if (!(p.x >= f.x + 8 && p.right <= f.right - 8 && p.y >= f.y + 8 && p.bottom <= f.bottom - 8)) failures.push(width + ': wallet panel escapes wood inner frame');
      await page.close();
    }
    assert.deepEqual(failures, []);
    console.log('wallet-frame-case: initial island status and framed wallet panel at 1440/390');
  } finally { if (browser) await browser.close(); assert.deepEqual(await HOSTS.finish(), []); }
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
