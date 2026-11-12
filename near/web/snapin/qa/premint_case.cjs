// Premint sheets: the five premint personas and the guide's claim step, in a real browser at 1440 and 390.
// For each battle option, through board 1's guide: "Use this preset" fetches that option's premint sheet, recomputes the
// digest with sheet.js and claims it (premint/meta/options.json); the Personality step carries the claimed name; the sheet
// the guide would send is the premint file byte for byte (sheet.js digest == published); an edit changes the digest; a
// tampered file is refused; a missing index turns claiming off with a plain message and the way on. Also: every name passes
// the guard, and the folder passes check_personas. (Board 1 draws no persona card on the Fighter or Personality step.)
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/premint_case.cjs [out-dir]
'use strict';
const { spawn, execFileSync } = require('child_process'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..'), PM = path.join(REPO, 'near/web/snapin/premint');
const OUT = process.argv[2] || path.join(os.tmpdir(), 'snapin-premint'); fs.mkdirSync(OUT, { recursive: true });
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
(async () => {
  // ---- the folder itself
  let dir = ''; try { dir = execFileSync('python3', ['-I', 'near/lore/check_personas.py', '--dir', PM], { cwd: REPO }).toString(); } catch (e) { dir = String(e.stdout || ''); }
  ok(/5\/5 valid\s*$/.test(dir), `check_personas --dir premint: "${dir.trim().split('\n').pop()}"`);
  const opts = JSON.parse(fs.readFileSync(path.join(PM, 'meta/options.json'), 'utf8'));
  ok(JSON.stringify(Object.keys(opts).sort()) === JSON.stringify(['brawler-swing', 'brawler-zap', 'hunter-lunge', 'looter-lob', 'survivor-beam']), 'options.json holds exactly the five battle options');
  const tops = fs.readdirSync(PM).filter((f) => f.endsWith('.json')).sort();
  ok(JSON.stringify(tops) === JSON.stringify(Object.values(opts).map((o) => o.file).sort()), `the five files at premint/'s top are exactly options.json's (${tops.join(', ')})`);
  const tags = Object.values(opts).map((o) => [o.name, JSON.parse(fs.readFileSync(path.join(PM, o.file), 'utf8')).game.tag]);
  ok(tags.every(([n, t]) => t === n.split(' ')[0] && !/[0-9]/.test(t)), `every premint tag is the persona's first name, no digits: ${tags.map((x) => x[1]).join(', ')}`);
  for (const [id, o] of Object.entries(opts)) {
    const py = execFileSync('python3', ['-I', 'near/lore/check_personas.py', '--digest', path.join(PM, o.file)], { cwd: REPO }).toString().trim();
    ok(py === o.digest, `${id}: check_personas --digest ${o.file} = options.json digest ${o.digest.slice(0, 12)}…`);
  }
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', 'http://127.0.0.1:9'], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const p = await (await b.newContext()).newPage(); const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  p.on('response', (r) => { if (r.status() >= 400) errs.push('http ' + r.status() + ' ' + r.url().replace(base, '')); });
  const ready = () => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
  const click = async (act) => { await p.click(`[data-act="${act}"]`); await sleep(200); };
  const fresh = async () => { await p.goto(base + '/web/snapin/index.html?step=wallet'); await ready(); await p.evaluate(() => { localStorage.clear(); sessionStorage.clear(); }); await p.reload(); await ready(); await click('g:wallet:dev-throwaway'); };
  try {
    const names = await (async () => { await p.goto(base + '/web/snapin/index.html?step=wallet'); await ready(); return p.evaluate((o) => Object.values(o).map((x) => [x.name, SnapSheet.guard(x.name).ok]), opts); })();
    ok(names.every((x) => x[1]), `every premint name passes the guard: ${names.map((x) => x[0]).join(', ')}`);
    let W = 1440;
    for (const [id, o] of Object.entries(opts)) {
      W = W === 1440 ? 390 : 1440; await p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
      await fresh();
      await click('g:preset:' + o.option);
      if (id === 'hunter-lunge') await p.screenshot({ path: path.join(OUT, `presets-${id}-${W}.png`), fullPage: true });
      await click('g:use'); await p.waitForFunction(() => Snapin.view.step === 'personality', null, { timeout: 10000 });
      const st = await p.evaluate(async () => { const sh = Snapin.buildSheet(); return { claim: Snapin.state.claim && Snapin.state.claim.digest, name: Snapin.state.name, dg: await SnapSheet.digest(sh), sheet: JSON.stringify(sh) }; });
      const file = JSON.stringify(JSON.parse(fs.readFileSync(path.join(PM, o.file), 'utf8')));
      ok(st.claim === o.digest && st.dg === o.digest && st.sheet === file && st.name === o.name,
        `${W} ${id}: claiming names ${o.digest.slice(0, 12)}…; the sheet the guide sends is ${o.file} byte for byte (sheet.js digest ${st.dg.slice(0, 12)}…)`);
      if (id === 'hunter-lunge') {
        await p.screenshot({ path: path.join(OUT, `claimed-${id}-${W}.png`), fullPage: true });
        await p.fill('#name', 'Pike Pennywhistler'); await sleep(400);
        const ed = await p.evaluate(async () => ({ dg: await SnapSheet.digest(Snapin.buildSheet()) }));
        ok(ed.dg !== o.digest, `${W} ${id}: an edit makes it the player's own persona: the sheet's digest changes (${ed.dg.slice(0, 12)}…)`);
      }
    }
    // a tampered file is refused
    await fresh();
    const o = opts['looter-lob'];
    await p.route('**/premint/' + o.file, async (r) => { const j = JSON.parse(fs.readFileSync(path.join(PM, o.file), 'utf8')); j.game.name = 'Coconut Cassie'; r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(j) }); });
    await click('g:preset:' + o.option);
    await click('g:use'); await sleep(800);
    const tam = await p.evaluate(() => ({ step: Snapin.view.step, fb: document.querySelector('#feedback').textContent, claim: !!(Snapin.state.claim && Snapin.state.claim.digest) }));
    ok(tam.step === 'presets' && !tam.claim && /does not match its published digest, so it cannot be claimed/.test(tam.fb), `a persona file that does not match its digest is refused: "${tam.fb}"`);
    await p.unroute('**/premint/' + o.file);
    // a missing index turns claiming off, plainly
    await p.route('**/premint/meta/options.json', (r) => r.fulfill({ status: 404, contentType: 'text/plain', body: 'nf' }));
    await fresh(); await sleep(800); await click('g:use'); await sleep(600);
    const miss = await p.innerText('#app');
    ok(/The premint personas could not be read \(answered 404\)\. Claiming is off until they can; Build a fighter still works\./.test(miss) && !!(await p.$('[data-act="g:build"]')) && (await p.evaluate(() => Snapin.view.step)) === 'presets', 'a missing premint index turns claiming off with a plain message and the way on (Build a fighter)');
    const own = errs.filter((e) => !/^http 404 \/web\/snapin\/premint\/meta\/options\.json$/.test(e) && !/^http 502 /.test(e));
    ok(own.length === 0, 'no page errors or failed requests beyond the test-supplied 404' + (own.length ? ': ' + own.slice(0, 4).join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); try { await p.screenshot({ path: path.join(OUT, 'crash.png'), fullPage: true }); } catch (e2) { /* gone */ } }
  await b.close().catch(() => {}); web.child.kill();
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed; frames in ${OUT}`);
  process.exit(fail ? 1 : 0);
})();
