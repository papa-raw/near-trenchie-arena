// Board 1's guide states, each reached through the real guide on the real DEV arena, each read off the screen and compared
// line by line with SPEC.md's copy for that state (the drawing's own words), at 1440 (exact, in order) and at 390 (every
// line the phone shows, in order; the phone hides "Keep watching" by design).
//   The SPEC draws one sample trenchie; its sample values are swapped for this run's real ones before comparing: the
//   wallet id, the name the guide picked, the one-time code and its SNAP.md address. "Lantern Lou is in the ring" happens
//   for real here: an agent session snaps Barnacle Bertie in first, so the guide's Brawler Swing claim picks another name.
//   key-codex is not offered until its browser (CORS) check passes; the case checks that the row is absent instead.
//   wallet-mainnet is drawn under two labelled fixtures: the host's /dev/health reports a mainnet identity network, and a
//   signed-in wallet is set as a real sign-in sets it (that needs a real wallet).
// The provider's answers to Test are the case's (no key, no spend). SPEC.md is passed as an argument or read from SPEC_MD.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/board1_guide_case.cjs <SPEC.md>
'use strict';
const path = require('path'), fs = require('fs'), os = require('os'), { execFileSync } = require('child_process');
const { chromium } = require('playwright');
const HOSTS = require('./hosts.cjs');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SPEC = process.argv[2] || process.env.SPEC_MD;
if (!SPEC || !fs.existsSync(SPEC)) { console.log('FAIL give the path to SPEC.md (argument or SPEC_MD)'); process.exit(1); }
// ---- the SPEC's copy blocks: ### `state` ... ``` lines ```
const COPY = {};
fs.readFileSync(SPEC, 'utf8').split(/\n### `/).slice(1).forEach((sec) => { const id = sec.slice(0, sec.indexOf('`')), m = sec.match(/```\n([\s\S]*?)\n```/); if (m) COPY[id] = m[1].split('\n').map((l) => l.trim()).filter(Boolean); });
const TMP = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'board1-guide-'));
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await HOSTS.start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await HOSTS.start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m, guide = base + '/web/snapin/index.html';
  const snap = (dir, ...a) => { fs.mkdirSync(dir, { recursive: true }); try { return execFileSync('python3', ['-I', path.join(HOSTS.REPO, 'near/arena/snap.py'), '--url', arenaUrl, '--state', path.join(dir, 'state.json'), ...a], { cwd: dir, timeout: 120000, stdio: ['ignore', 'pipe', 'pipe'] }).toString(); } catch (e) { return 'ERR ' + String(e.stdout || '') + String(e.stderr || e.message).slice(0, 300); } };
  let b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const errs = [];
  try {
    // the sheet's sample fighter is in the ring already (an agent session), so the guide's claim of it picks a free name
    const bertie = snap(path.join(TMP, 'bertie'), 'join', '--name', 'Barnacle Bertie', '--preset', 'brawler-swing', '--accept-terms', '1');
    ok(/"joined": true/.test(bertie), 'an agent session snapped Barnacle Bertie in first');
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
    let answer = 200, shortExpiry = false;
    await ctx.route('https://cloud-api.near.ai/**', (r) => r.request().method() === 'OPTIONS' ? r.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'POST' } })
      : r.fulfill({ status: answer, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: answer === 200 ? JSON.stringify({ choices: [{ message: { content: 'Ahoy! Ready when you are.' } }] }) : answer === 401 ? '{"error":{"message":"invalid api key"}}' : '{"error":{"message":"insufficient credits on billing"}}' }));
    // plan-expired: the case shortens the one-time code's life (the arena's own is 10 min)
    await ctx.route('**/snap/code', async (r) => { if (r.request().method() !== 'POST' || !shortExpiry) return r.continue(); const res = await r.fetch(), j = await res.json(); j.expires_at = Date.now() + 3000; r.fulfill({ response: res, body: JSON.stringify(j) }); });
    const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(e.message));
    let cur = p;   // the page check() reads
    const act = async (x) => { await p.click(`[data-act="${x}"]`); await sleep(350); };
    // the board keeps "0.5 s" and "3 tiles" together with a no-break space; SPEC.md writes a plain one
    const lines = async () => (await cur.evaluate(() => document.querySelector('#app').innerText)).replace(/\u00a0/g, ' ').split('\n').map((l) => l.trim()).filter(Boolean);
    const S = {};   // this run's values for the SPEC's sample ones
    const swap = (l) => {
      // Pat's verdict (2026-11-13 08:55): "Trenchie" is capitalised in all user-facing text; SPEC.md still writes "trenchie"
      l = l.replace(/(?<![\w.\-/])trenchie(s?)(?![\w\-/]|\.\w)/g, 'Trenchie$1');   // not inside a key or a URL (trenchie.snapin, near-trenchie)
      if (S.wallet) l = l.split('tidepool42.testnet').join(S.wallet);
      if (S.name) l = l.split('Barnacle Bertie of the Low Tide').join(S.name);
      l = l.replace('Lantern Lou is in the ring', 'Barnacle Bertie is in the ring');
      if (S.code && /^(claude|codex) "Join Trenchie Arena/.test(l)) l = l.replace('https://neartrenchies.xyz/SNAP.md', S.snap).replace('K7QF-2M9D', S.code);
      return l;
    };
    const same = (want, got) => { if (want === got) return true;
      if (/^Bertie “/.test(want)) return /^\S+ “.+”$/.test(got);                                    // the sample line in the trenchie's own voice
      if (/Waiting for your session · the code ends in/.test(want)) return /^Waiting for your session · the code ends in \d+:\d\d$/.test(got);
      return false; };
    async function check(id, note, drop) {
      let want = (COPY[id] || []).map(swap); if (drop) want = drop(want);
      const got1440 = await lines();
      await cur.setViewportSize({ width: 390, height: 844 }); await sleep(600); const got390 = await lines();
      await cur.setViewportSize({ width: 1440, height: 900 }); await sleep(400);
      const exact = want.length === got1440.length && want.every((w, i) => same(w, got1440[i]));
      let j = 0; got390.forEach((g) => { if (j < want.length && same(want[j], g)) j++; else if (j < want.length && want[j] === 'Keep watching') { j++; if (same(want[j], g)) j++; } });
      const phone = j >= want.length - (want.includes('Keep watching') ? 1 : 0);
      const diff = exact ? '' : ' | first difference: ' + JSON.stringify((() => { for (let i = 0; i < Math.max(want.length, got1440.length); i++) if (!same(want[i], got1440[i])) return [i, want[i], got1440[i]]; return []; })());
      ok(want.length > 0 && exact && phone, `${id}: the screen's copy is SPEC's, line for line (${want.length} lines at 1440${phone ? '; all in order at 390' : '; NOT all at 390'})${note ? ' ' + note : ''}${diff}`);
    }
    // ---- step 1, 2, 3
    await p.goto(guide + '?step=wallet'); await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
    await act('g:wallet:dev-throwaway'); S.wallet = await p.evaluate(() => { const a = Snapin.state.wallet.accountId; return a.length > 28 ? a.slice(0, 12) + '…' + a.slice(-8) : a; });
    await act('g:step:wallet'); await check('wallet');
    await act('g:step:presets'); await check('fighter');
    await act('g:use'); await p.waitForFunction(() => Snapin.view.step === 'personality' && /✓ Free/.test(document.body.innerText), null, { timeout: 20000 }).catch(() => {});
    S.name = await p.evaluate(() => Snapin.state.name);
    await act('g:temper:sunny'); for (const q of await p.evaluate(() => Snapin.state.quirks.slice())) await act('g:quirk:' + q); await act('g:quirk:sea-puns');
    await check('persona', `(the guide picked "${S.name}")`);
    // ---- step 4: the doors, NEAR AI Cloud's key screen in each of its states
    // the Codex KEY row is shown only once its browser (CORS) check passes (SPEC key-codex); until then the list is SPEC's without it
    const codexKey = !!(await p.evaluate(() => window.SnapProviders && SnapProviders.codex && SnapProviders.codex.corsChecked));
    await act('g:step:doors');
    await check('doors', codexKey ? '' : '(without the Codex KEY row: its browser check has not passed)', codexKey ? null : (w) => { const i = w.findIndex((l, k) => l === 'Codex' && w[k + 1] === 'KEY'); return i >= 0 ? w.slice(0, i).concat(w.slice(i + 2)) : w; });
    ok(codexKey === !!(await p.$('[data-act="g:door:key:Codex"]')), 'key-codex: the Codex key row is offered exactly when its browser (CORS) check has passed (' + (codexKey ? 'passed: offered' : 'not passed: not offered') + ')');
    await act('g:door:key:NEAR AI Cloud'); await check('key-empty');
    await p.fill('#key', 'sk-case-not-a-real-key-6986'); answer = 401; await act('g:test'); await sleep(600); await check('key-wrong');
    await p.fill('#key', 'sk-case-not-a-real-key-6986'); answer = 403; await act('g:test'); await sleep(600); await check('key-nocredit');
    // the other key doors, seen as a new player sees them (no cap picked yet)
    await act('g:other'); await act('g:door:key:Claude'); await check('key-claude');
    await act('g:other'); await act('g:door:key:OpenRouter'); await check('key-openrouter');
    await act('g:other'); await act('g:door:key:NEAR AI Cloud');
    await p.fill('#key', 'sk-case-not-a-real-key-6986'); answer = 200; await act('g:test'); await sleep(600);
    // ---- step 5 before a cap: blocked, naming the cap; then the cap, the key screen answered, the check page ready
    await act('g:step:agree'); await p.waitForFunction(() => Snapin.view.terms && Snapin.view.terms.version, null, { timeout: 20000 }).catch(() => {}); await sleep(300); await check('check-blocked');
    await act('g:ai'); await act('g:cap:0.20'); await check('key-ok');
    await act('g:step:agree'); await sleep(500); await check('check-ready');
    // ---- the plan doors
    await act('g:step:doors');
    const plan = async (door) => { await act('g:other'); await act('g:door:plan:' + door); await p.waitForFunction(() => /code ends in \d/.test(document.body.innerText), null, { timeout: 20000 }).catch(() => {});
      const c = await p.evaluate(() => SnapGuide.state.code); S.code = c && c.code; S.snap = c && c.snapUrl; };
    await plan('Claude Code'); await check('plan-claude');
    await plan('Codex'); await check('plan-codex');
    shortExpiry = true; await plan('Claude Code'); shortExpiry = false; await sleep(4500); await check('plan-expired');
    await act('g:newcode'); await p.waitForFunction(() => /code ends in \d/.test(document.body.innerText), null, { timeout: 20000 }).catch(() => {});
    const c2 = await p.evaluate(() => SnapGuide.state.code); S.code = c2 && c2.code; S.snap = c2 && c2.snapUrl;
    // the player's agent session joins with the door's code (snap.py live --code: battle mode, as SNAP.md's recipe runs it)
    fs.mkdirSync(path.join(TMP, 'agent'), { recursive: true });
    const live = HOSTS.host(['-I', path.join(HOSTS.REPO, 'near/arena/snap.py'), '--url', arenaUrl, '--state', path.join(TMP, 'agent', 'state.json'), 'live', '--code', S.code, '--name', S.name.replace(/ \d+$/, '') + ' Agent', '--preset', 'brawler-swing', '--accept-terms', '1', '--seconds', '60'], { cwd: path.join(TMP, 'agent'), stdio: ['pipe', 'pipe', 'pipe'] });
    let liveOut = ''; live.stdout.on('data', (d) => { liveOut += d; }); live.stderr.on('data', (d) => { liveOut += d; });
    await p.waitForFunction(() => /session joined/.test(document.body.innerText), null, { timeout: 45000 }).catch(() => {});
    await check('plan-joined', `(the agent session joined with the code: ${liveOut.split('\n')[0].slice(0, 60)})`);
    live.kill(); snap(path.join(TMP, 'bertie'), 'stop');
    // ---- wallet-mainnet, on two labelled fixtures: the host reports its identity network as mainnet (the case's answer to
    // /dev/health, which keeps the host's own fields), and a wallet's sign-in result is set as a real sign-in sets it (that
    // needs a real wallet). The step is the page's own drawing under a mainnet host. A fresh browser: one single-process
    // Chromium does not survive a second context.
    await b.close().catch(() => {}); b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
    const ctxM = await b.newContext({ viewport: { width: 1440, height: 900 } });
    await ctxM.route('**/dev/health', async (r) => { const res = await r.fetch(); let j = {}; try { j = await res.json(); } catch (e) { /* none */ } j.chain_mode = { identity_network: 'mainnet', identity_nft: 'trenchie-nft.fixture.near' }; r.fulfill({ response: res, body: JSON.stringify(j) }); });
    cur = await ctxM.newPage(); cur.on('pageerror', (e) => errs.push('mainnet page: ' + e.message));
    await cur.goto(guide + '?step=wallet'); await cur.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
    await cur.waitForFunction(() => /MAINNET/.test(document.querySelector('#app').innerText), null, { timeout: 20000 }).catch(() => {});
    await cur.evaluate(() => { Snapin.state.wallet = { id: 'meteor', accountId: 'tidepool42.near', network: 'mainnet' }; });
    await cur.click('[data-act="g:step:wallet"]'); await sleep(400);
    await check('wallet-mainnet', '(fixtures: a mainnet host, and a signed-in tidepool42.near)');
    ok(!(await cur.$('[data-act="g:wallet:dev-throwaway"]')), 'wallet-mainnet: no throwaway account on a chain host');
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.stack || e).slice(0, 500)); }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  fs.rmSync(TMP, { recursive: true, force: true });
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
