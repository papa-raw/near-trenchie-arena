// Real-browser evidence for the login doors (fake keys only).
//   export NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules
//   node near/web/snapin/spike/run-doors.cjs [out-prefix]
// Starts a loopback http.server (serving near/web/snapin/) and spike/snap-stub.py, launches ONE headless
// Chromium (single-process, as the lane needs), loads spike/doors.html, prints the results, closes the
// browser, and ALWAYS kills both servers before it exits. Outbound calls go through the lane proxy.
'use strict';
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const { chromium } = require('playwright');

const SNAPIN = path.resolve(__dirname, '..');
const WEB = 8831, STUB = 8832;
const prefix = process.argv[2] || path.join(process.env.TMPDIR || '/tmp', 'doors');
const kids = [];
const up = (port, p) => new Promise((res, rej) => {
  const t0 = Date.now();
  (function tick() {
    http.get({ host: '127.0.0.1', port, path: p }, (r) => { r.resume(); res(); }).on('error', () => (Date.now() - t0 > 8000 ? rej(new Error('server ' + port + ' did not start')) : setTimeout(tick, 150)));
  })();
});

(async () => {
  let browser;
  try {
    kids.push(spawn('python3', ['-m', 'http.server', String(WEB), '--bind', '127.0.0.1', '--directory', SNAPIN], { stdio: 'ignore' }));
    kids.push(spawn('python3', ['-I', path.join(__dirname, 'snap-stub.py'), String(STUB)], { stdio: 'inherit' }));
    await Promise.all([up(WEB, '/spike/doors.html'), up(STUB, '/SNAP.md')]);
    const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
    browser = await chromium.launch({
      args: ['--single-process', '--no-zygote', '--use-gl=angle', '--use-angle=swiftshader-webgl', '--enable-unsafe-swiftshader'],
      proxy: proxy ? { server: proxy, bypass: '127.0.0.1,localhost' } : undefined,
    });
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errs = [];
    page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) errs.push(m.type() + ': ' + m.text().slice(0, 200)); });
    page.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
    await page.goto(`http://127.0.0.1:${WEB}/spike/doors.html?stub=${encodeURIComponent('http://127.0.0.1:' + STUB)}`);
    await page.waitForFunction(() => window.__DONE === true, null, { timeout: 90000 });
    const res = await page.evaluate(() => window.__RESULTS);
    await page.screenshot({ path: prefix + '.png', fullPage: true });
    require('fs').writeFileSync(prefix + '.json', JSON.stringify({ res, consoleErrors: errs }, null, 1));
    console.log('origin', res.origin, '\nuserAgent', res.userAgent);
    for (const r of res.rows) {
      console.log(`#${r.n} ${r.door}\n   url=${r.url}\n   type=${r.type} status=${r.status}${r.error ? ' error=' + r.error : ''}\n   acHeaders=${JSON.stringify(r.acHeaders)}\n   parsed=${JSON.stringify(r.parsed)}`);
    }
    console.log('wallet', JSON.stringify(res.wallet));
    console.log('console errors/warnings:', JSON.stringify(errs));
  } finally {
    if (browser) await browser.close().catch(() => {});
    for (const k of kids) { try { k.kill('SIGTERM'); } catch (e) {} }
  }
})().catch((e) => { console.error('run-doors failed:', e.message); for (const k of kids) { try { k.kill('SIGKILL'); } catch (x) {} } process.exit(1); });
