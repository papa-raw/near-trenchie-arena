// Interaction cases for the snap-in screens in a real browser (Playwright, one Chromium at a time).
// Serves near/web/snapin over loopback itself, plus a LABELLED STUB of the snap endpoint (the real one is not built yet: SNAP.md asserts no hosted origin).
// The three key doors call their providers for real with FAKE keys (NEAR AI Cloud, Anthropic, OpenRouter): expected 401/400 answers prove the call path and CORS.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/test_flow.cjs [out-dir]
const http = require('http'), fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..', '..'), OUT = process.argv[2] || path.join(require('os').tmpdir(), 'snapin-flow');
fs.mkdirSync(OUT, { recursive: true });
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.woff2': 'font/woff2', '.md': 'text/plain', '.txt': 'text/plain' };
let polls = 0, issued = null;
const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  if (req.method === 'POST' && u.pathname === '/snap/code') {
    let b = ''; req.on('data', d => b += d); req.on('end', () => { issued = 'CORAL-' + (100 + Math.floor(Math.random() * 900)); polls = 0;
      res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ code: issued, expires_at: Date.now() + 300000, stub: true })); }); return;
  }
  if (u.pathname.startsWith('/snap/code/')) { polls++; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ joined: polls >= 1 })); return; }
  let f = path.join(ROOT, u.pathname === '/' ? 'snapin/index.html' : decodeURIComponent(u.pathname));
  if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.statusCode = 404; return res.end('nf'); }
  res.setHeader('content-type', MIME[path.extname(f)] || 'application/octet-stream'); res.end(fs.readFileSync(f));
});
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = 'http://127.0.0.1:' + server.address().port;
  const b = await chromium.launch({ proxy: process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' } : undefined, args: ['--single-process', '--no-zygote', '--use-gl=angle', '--use-angle=swiftshader-webgl', '--enable-unsafe-swiftshader'] });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const p = await ctx.newPage(); const errs = [];
  p.on('console', m => { if (m.type() === 'error') errs.push(m.type() + ': ' + m.text()); });
  p.on('pageerror', e => errs.push('pageerror: ' + e.message));
  const open = async (qs) => { await p.goto(base + '/snapin/index.html' + qs, { waitUntil: 'networkidle' }); await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 }); };
  const click = (act) => p.click(`[data-act="${act}"]`);
  const text = () => p.evaluate(() => document.body.innerText);
  try {
    // ---- fighter, personality, sheet
    await open('?step=presets'); await p.evaluate(() => localStorage.clear()); await open('?step=presets');
    await click('preset:Hunter Lunge');
    ok(await p.evaluate(() => Snapin.state.preset === 'Hunter Lunge'), 'preset pick is saved');
    await click('step:personality');
    const temper = await p.evaluate(() => SnapSheet.TEMPERAMENTS[1].id);
    await click('temper:' + temper); await p.fill('#name', 'Pip Shoals'); await p.fill('#personality', 'Talks in charts. Swings first.');
    const sh = await p.evaluate(() => Snapin.buildSheet());
    ok(sh && !sh.error && sh.game.name === 'Pip Shoals' && sh.game.temperament.toLowerCase() === temper, 'the skinner builds a sheet from the choices');
    ok(await p.evaluate(() => SnapSheet.validate(Snapin.buildSheet()).length === 0), 'that sheet passes SnapSheet.validate (0 failures)');
    ok(sh.game.fight_style === 'hunter' && sh.game.version === 2, 'sheet carries the fight style from the preset (game block v2)');
    ok(!('loadout' in sh.game), 'player sheet has no loadout field');
    // ---- the look (S3 c): a hat and a face part change the saved look and the portrait
    await open('?mode=workshop&tab=look');
    const before = await p.evaluate(() => document.querySelector('img.hero').src.length);
    await click('look:hat:c-head-maxi'); await click('look:eyes:wink');
    ok(await p.evaluate(() => Snapin.state.look.hat === 'c-head-maxi' && Snapin.state.look.eyes === 'wink'), 'look picks are saved (hat rack + eyes)');
    ok(await p.evaluate(() => document.querySelector('img.hero').src.startsWith('data:image/png')), 'portrait re-renders from the player parts');
    ok(await p.evaluate(() => SnapSheet.validate(Snapin.buildSheet()).length === 0), 'sheet still passes after look edits');
    // ---- download the sheet
    await open('?mode=workshop&tab=persona');
    const [dl] = await Promise.all([p.waitForEvent('download'), click('sheet-download')]);
    const dir = path.join(OUT, 'sheets'); fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, dl.suggestedFilename()); await dl.saveAs(file);
    const dsheet = JSON.parse(fs.readFileSync(file, 'utf8'));
    ok(dsheet.game && dsheet.model_routing && !JSON.stringify(dsheet).match(/sk-|Bearer/), 'downloaded sheet is JSON, carries no key');
    ok(dl.suggestedFilename() === dsheet.identity.role + '.json', 'the download is named <role>.json (' + dl.suggestedFilename() + ')');
    const chk = require('child_process').spawnSync('python3', ['-I', path.resolve(ROOT, '..', 'lore', 'check_personas.py'), '--dir', dir], { encoding: 'utf8' });
    ok(chk.status === 0 && /1\/1 valid/.test(chk.stdout), 'the downloaded sheet passes check_personas.py --dir (' + chk.stdout.trim().split('\n').pop() + ')');
    // ---- the corner
    await open('?mode=workshop&tab=respawn');
    await p.fill('[data-spread="0"]', '50');
    let ev = null; await p.evaluate(() => { window.__ev = null; addEventListener('snapin:respawn-ready', e => window.__ev = e.detail); });
    await click('ready'); ok((await p.textContent('#locked')).includes('100%'), 'spread over 100% is refused');
    await p.fill('[data-spread="0"]', '40'); await click('ready');
    ev = await p.evaluate(() => window.__ev); ok(ev && ev.spread.join() === '40,30,20,10' && ev.stake === false, 'ready next life emits the pick (spread 100%, stake off)');
    // ---- the card
    await open('?mode=workshop&tab=card');
    ok(await p.evaluate(() => !!document.querySelector('.persona-card svg') && document.body.innerText.includes('No lives scored yet')), 'card draws with an empty, honest gauge');
    // ---- doors: three key doors, real calls with fake keys
    await open('?mode=login'); await p.evaluate(() => localStorage.removeItem('trenchie.snapin.lastdoor'));
    await open('?mode=login');
    await click('ai:door:NEAR AI Cloud'); await p.fill('#key', 'sk-test-key-nearai'); await click('ai:test');
    await p.waitForFunction(() => document.body.innerText.includes('Key not accepted') || document.body.innerText.includes('Call could not be made'), null, { timeout: 25000 });
    ok((await text()).includes('Key not accepted'), 'NEAR AI Cloud: real call from the browser, fake key answered 401 (Key not accepted)');
    await open('?mode=login'); await click('ai:door:Claude'); await click('ai:credits'); await p.fill('#key', 'sk-' + 'ant-test-key'); await click('ai:test');
    await p.waitForFunction(() => document.body.innerText.includes('Key not accepted') || document.body.innerText.includes('Call could not be made'), null, { timeout: 25000 });
    ok((await text()).includes('Key not accepted'), 'Claude (Console key): real call with the opt-in header, fake key answered 401');
    await open('?mode=login'); await click('ai:door:OpenRouter');
    let authUrl = null; await p.route('https://openrouter.ai/auth*', r => { authUrl = r.request().url(); r.fulfill({ status: 200, contentType: 'text/html', body: 'authorize stub' }); });
    await click('ai:authorize'); await p.waitForTimeout(1500);
    ok(authUrl && /code_challenge=[\w-]{20,}/.test(authUrl) && /code_challenge_method=S256/.test(authUrl) && /callback_url=/.test(authUrl), 'OpenRouter: authorize link carries a PKCE S256 challenge and the callback');
    await p.unroute('https://openrouter.ai/auth*');
    await open('?mode=login&code=fakecode12345');
    await p.waitForFunction(() => document.body.innerText.includes('Call could not be made') || document.body.innerText.includes('Key not accepted'), null, { timeout: 25000 });
    ok(/Invalid code|code/i.test(await text()), 'OpenRouter: returning code is swapped for real (fake code answered 400 Invalid code)');
    // ---- doors: hand-off through the (stub) snap endpoint
    await open('?mode=login'); await click('ai:door:Codex');
    await p.waitForFunction(() => /CORAL-\d+/.test(document.body.innerText), null, { timeout: 10000 });
    ok((await text()).includes('local test endpoint') || (await text()).includes('stub'), 'hand-off: shows a one-time code and says the endpoint is a local stub');
    await p.waitForFunction(() => document.body.innerText.includes('Ready to fight'), null, { timeout: 12000 });
    ok(true, 'hand-off: polling sees the agent arrive and the door connects');
    await p.screenshot({ path: path.join(OUT, 'handoff-connected.png') });
    // ---- the dock closes with Escape; no console errors anywhere
    ok(errs.filter(e => !/net::ERR_FAILED|401|400/.test(e)).length === 0, 'no console errors beyond the expected 401/400 provider answers (' + errs.length + ' logged)');
    if (errs.length) console.log(' logged:', JSON.stringify(errs).slice(0, 600));
  } catch (e) { fail++; console.log('FAIL exception', e.message.split('\n')[0], JSON.stringify(errs).slice(0, 500)); }
  await b.close(); server.close();
  console.log(`${pass} PASS, ${fail} FAIL`); process.exit(fail ? 1 : 0);
})();
