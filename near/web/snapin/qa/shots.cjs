// Real-browser pass over every snap-in screen at 1440 and 390: screenshots, console errors, horizontal overflow.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/shots.cjs <out-dir> [filter]
// One browser per capture (single-process Chromium cannot open a second page). Exit 1 on any console error, failed request or overflow.
const { chromium } = require('playwright');
const fs = require('fs'), http = require('http'), path = require('path');
const [out, filter] = process.argv.slice(2);
// serves near/web/snapin itself over loopback (no external server to leave running)
const ROOT = path.resolve(__dirname, '..', '..');   // near/web: the page imports ../art and ../vendor/three
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.woff2': 'font/woff2' };
const server = http.createServer((req, res) => { const u = new URL(req.url, 'http://x'); const f = path.join(ROOT, u.pathname === '/' ? 'snapin/index.html' : decodeURIComponent(u.pathname));
  if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.statusCode = 404; return res.end('nf'); } res.setHeader('content-type', MIME[path.extname(f)] || 'application/octet-stream'); res.end(fs.readFileSync(f)); });
let base = '';
const CASES = [
  ['flow-watch', ''], ['flow-wallet', '?step=wallet'], ['flow-presets', '?step=presets'], ['flow-build', '?step=build'], ['flow-personality', '?step=personality'],
  ['flow-doors', '?step=doors'], ['flow-agree', '?step=agree'], ['flow-ring', '?step=ring'], ['flow-claimed', '?step=claimed'],
  ['login-doors', '?mode=login'], ['login-claude', '?mode=login&ai=claude&door=Claude'], ['login-handoff', '?mode=login&ai=handoff&door=Codex&route=plan'],
  ['login-near', '?mode=login&ai=near&door=NEAR%20AI%20Cloud'], ['login-credits', '?mode=login&ai=credits&door=Claude'], ['login-router', '?mode=login&ai=router&door=OpenRouter'],
  ['login-connected', '?mode=login&ai=connected&door=Codex&route=plan'], ['login-bad-key', '?mode=login&ai=bad-key&door=NEAR%20AI%20Cloud'],
  ['login-no-credits', '?mode=login&ai=no-credits&door=OpenRouter'], ['login-key-expired', '?mode=login&ai=key-expired&door=Claude'], ['login-disconnected', '?mode=login&ai=disconnected&door=Codex&route=plan'],
  ['work-battle', '?mode=workshop&tab=battle'], ['work-inventory', '?mode=workshop&tab=inventory'], ['work-look', '?mode=workshop&tab=look'], ['work-persona', '?mode=workshop&tab=persona'],
  ['work-card', '?mode=workshop&tab=card'], ['work-agree', '?mode=workshop&tab=agree'], ['work-respawn', '?mode=workshop&tab=respawn']
].filter(c => !filter || c[0].includes(filter));
(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r)); base = 'http://127.0.0.1:' + server.address().port;
  fs.mkdirSync(out, { recursive: true });
  let bad = 0;
  for (const [name, qs] of CASES) for (const [w, h] of [[1440, 900], [390, 844]]) {
    const b = await chromium.launch({ args: ['--single-process', '--no-zygote', '--use-gl=angle', '--use-angle=swiftshader-webgl', '--enable-unsafe-swiftshader'] });
    const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    const errs = [];
    p.on('console', m => { if (m.type() === 'error') errs.push(m.type() + ': ' + m.text()); });
    p.on('pageerror', e => errs.push('pageerror: ' + e.message));
    p.on('requestfailed', r => errs.push('requestfailed: ' + r.url()));
    p.on('response', r => { if (r.status() >= 400) errs.push('http ' + r.status() + ': ' + r.url()); });
    await p.goto(base + '/snapin/index.html' + qs, { waitUntil: 'networkidle' });
    await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 }).catch(() => errs.push('never ready'));
    await p.waitForTimeout(500);
    await p.screenshot({ path: `${out}/${name}-${w}.png`, fullPage: true });
    const over = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
    if (over.sw > over.iw + 1) errs.push(`horizontal overflow ${over.sw} > ${over.iw}`);
    if (errs.length) bad++;
    console.log(errs.length ? 'FAIL' : 'ok  ', name, w, errs.length ? JSON.stringify(errs).slice(0, 400) : '');
    await b.close();
  }
  console.log(bad ? `${bad} captures with errors` : 'all captures clean');
  server.close(); process.exit(bad ? 1 : 0);
})();
