// Pat's click-through items 33 and 25 (2026-11-12): "I can't snap in with a different trenchie, it keeps going to bob",
// and "I went back and it dropped the whole flow". Every earlier snap-in case started from empty storage; this one starts
// from a RETURNING browser (one persistent Chromium profile reused across visits) on the real DEV arena, restarts the
// arena mid-case, and runs the guide once more in a private window whose storage is partly blocked.
//   1. visit 1: wallet, a premint claim, a name edited after the claim; Back to the Fighter step shows the player's own
//      trenchie (not the premint's default) and going on keeps the edited name (item 25); A snaps in through the guide
//      (the AI door's key answered "Say hi"; a cap is set).
//   2. visit 2 (same profile): the returning screen offers "Make a new trenchie"; it asks once in plain words (what it
//      forgets, that A swims home first, what is kept); "Keep" changes nothing; "Start fresh" says so at the top of the
//      screen, the swim home survives a reload, then B snaps in with a new name; the guide follows B; wallet, key, cap kept.
//   3. an agent-driven trenchie (snap.py, as Pat's Bob) stays in the ring beside a new browser trenchie made from the
//      guide's first screen; then every tab is closed until the seat ends: on return, and on two reloads, the draft still
//      holds the trenchie and the guide offers "Snap <name> back in" or "Make a new trenchie", sending no join.
//   4. the DEV arena restarts: the same offer says the arena restarted, the draft is kept through a reload, nothing is
//      retried; "Snap <name> back in" puts the same trenchie back in the ring.
//   5. a private window (IndexedDB missing, localStorage refusing writes): wallet to snapped in, one page load.
// The NEAR AI Cloud "Say hi" call is answered by the case (no key, no spend); everything else is the real local arena.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/new_trenchie_case.cjs
'use strict';
const { spawn, execFileSync } = require('child_process'), path = require('path'), fs = require('fs'), os = require('os');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TMP = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'new-trenchie-'));
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs'), G = require('./board1_flow.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
const KEYSTORE = 'trenchie.snapin.key.NEAR AI Cloud', FAKE_KEY = 'sk-case-not-a-real-key-0000';
// the AI door's "Say hi" (and any later brain call) gets a canned answer: the case never reaches a provider
async function fakeProvider(ctx) {
  await ctx.route('https://cloud-api.near.ai/**', (r) => r.request().method() === 'OPTIONS'
    ? r.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'POST' } })
    : r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ choices: [{ message: { content: 'hi' } }], usage: { prompt_tokens: 10, completion_tokens: 1 } }) }));
}
const ready = (p) => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
const text = (p) => p.evaluate(() => document.querySelector('#app').innerText);
const act = async (p, a) => { await p.click(`[data-act="${a}"]`); await sleep(250); };
const phase = (p) => p.evaluate(() => (window.SnapRoom && SnapRoom.status().phase) || '');
const draft = (p) => p.evaluate(() => { try { return localStorage.getItem('trenchie.snapin.v1') || ''; } catch (e) { return 'BLOCKED'; } });
const ls = (p, k) => p.evaluate((k2) => { try { return localStorage.getItem(k2); } catch (e) { return null; } }, k);
async function waitIn(p, ms) { try { await p.waitForFunction(() => window.SnapRoom && SnapRoom.status().phase === 'in', null, { timeout: ms || 45000 }); return true; } catch (e) { return false; } }
// board 1's path from the AI step to "Snap in": NEAR AI Cloud, the key (Test answered) or the one already saved, a cap,
// the check page, Snap in
async function doorAndAgree(p, typeKey) {
  await act(p, 'g:step:doors'); if (await p.$('[data-act="g:other"]')) await act(p, 'g:other');
  await act(p, 'g:door:key:NEAR AI Cloud');
  if (typeKey) { await p.fill('#key', FAKE_KEY); await act(p, 'g:test'); await p.waitForFunction(() => /It answered/.test(document.body.innerText), null, { timeout: 15000 }); }
  await act(p, 'g:cap:0.50');
  await act(p, 'g:step:agree'); await p.waitForFunction(() => Snapin.view.terms && Snapin.view.terms.version, null, { timeout: 15000 });
  const guideUrl = p.url(); await act(p, 'g:snap');
  // board 1: Snap in lands on the arena page's panel; this case's checks are on the guide's ring view, so it comes back
  await G.afterSnap(p, { guideUrl, backToGuide: true, timeout: 90000 }).catch((e) => console.log('  after Snap in:', e.message));
}
async function setName(p, name) { await p.fill('#name', name); await sleep(150); }
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  let arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m, guide = base + '/web/snapin/index.html';
  const ring = async () => { try { const o = await (await fetch(arenaUrl + '/room/observe')).json(); return (o.fighters || []).filter((f) => f.state === 'ring' || f.state === 'bench' || f.state === 'respawn').map((f) => String(f.public_name || '')); } catch (e) { return []; } };
  const states = async () => { try { const o = await (await fetch(arenaUrl + '/room/observe')).json(); return (o.fighters || []).filter((f) => !f.house).map((f) => f.public_name + ':' + f.state); } catch (e) { return [String(e)]; } };
  // an agent's fighter is labelled by its id ("DEV agentpip", item 30c), the guide's by its name: compare both ways
  const squash = (x) => String(x).toLowerCase().replace(/[^a-z0-9]/g, '');
  const inRing = async (name) => (await ring()).some((n) => /^DEV /.test(n) && squash(n.slice(4).split(' · ')[0]) === squash(name));
  const profile = path.join(TMP, 'profile'), agentDir = path.join(TMP, 'agent'); fs.mkdirSync(agentDir);
  let ctx = null, b2 = null;
  try {
    // ---------------------------------------------------------------- 1. visit 1: build A, go Back, snap in
    ctx = await chromium.launchPersistentContext(profile, { args: ['--single-process', '--no-zygote'] });
    await fakeProvider(ctx);
    let p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message));
    await p.goto(guide + '?step=wallet'); await ready(p);
    await p.evaluate(() => { localStorage.setItem('selected-wallet', 'case-wallet-marker'); });   // a wallet library's own key: must survive
    await act(p, 'g:wallet:dev-throwaway'); await act(p, 'g:use'); await p.waitForSelector('#name', { timeout: 15000 });
    await setName(p, 'Alfa Pip');
    await p.goBack(); await sleep(400);                                        // Back to the Fighter step (item 25)
    const back = await p.evaluate(() => Snapin.view.step), t1 = await text(p);
    // board 1's Fighter step names no persona at all: never the premint's default (Barnacle Bertie for Brawler Swing)
    ok(!/comes as/i.test(t1) && !/Barnacle Bertie/.test(t1), `after Back the Fighter step never shows the premint's default over the player's own trenchie`);
    await act(p, 'g:use'); await p.waitForSelector('#name', { timeout: 15000 });
    const kept = await p.inputValue('#name');
    ok(back === 'presets' && kept === 'Alfa Pip', `Back to the Fighter step and on again keeps the name typed after the claim (step ${back}, name "${kept}")`);
    await doorAndAgree(p, true);
    ok(await waitIn(p) && await inRing('Alfa Pip'), `visit 1: A (Alfa Pip) is in the ring (${(await ring()).filter((n) => /^DEV/.test(n)).join(', ')})`);
    const wallet1 = JSON.parse(await draft(p) || '{}').wallet;
    await p.close();

    // ---------------------------------------------------------------- 2. visit 2: the returning screen, Make a new trenchie
    p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(e.message));
    await p.goto(guide + '?step=ring&from=arena'); await ready(p);
    await p.waitForFunction(() => window.SnapRoom && SnapRoom.status().phase === 'in', null, { timeout: 30000 }).catch(() => {});
    const btnNew = await p.$('[data-act="new-trenchie"]');
    ok(!!btnNew, 'visit 2: the returning screen (A in the ring) offers "Make a new trenchie"');
    if (btnNew) {
      await act(p, 'new-trenchie');
      const ask = (await text(p)).replace(/\s+/g, ' ');
      ok(/This forgets Alfa Pip: its name, look, temperament, quirks and voice, and its premint claim\. Keep it or start fresh\?/.test(ask) && /Alfa Pip swims home first/.test(ask) && /Kept: your wallet, your AI door \(NEAR AI Cloud and its key\) and your hourly cap\./.test(ask),
        `it asks once in plain words, with what happens to A in the ring and what is kept ("${(ask.match(/This forgets.*?hourly cap\./) || [''])[0]}")`);
      await act(p, 'new-trenchie-no');
      ok(/Alfa Pip/.test(await draft(p)) && await phase(p) === 'in' && !(await p.$('.confirm-new')), '"Keep Alfa Pip" changes nothing: the draft and the fighter stay');
      await act(p, 'new-trenchie'); await act(p, 'new-trenchie-yes');
      await p.waitForFunction(() => Snapin.view.step === 'presets', null, { timeout: 20000 }).catch(() => {});
      await p.setViewportSize({ width: 390, height: 844 }); await sleep(300);
      const flash = await p.evaluate(() => { const b = [...document.querySelectorAll('.in-banner, .note')].find((x) => /is forgotten/.test(x.innerText)); return b ? { text: b.innerText.replace(/\s+/g, ' '), top: b.getBoundingClientRect().top, h: innerHeight } : null; });
      ok(!!flash && flash.top >= 0 && flash.top < flash.h, `the confirmation shows at the top of the screen at 390 px (${flash ? flash.text + ' @y=' + Math.round(flash.top) : 'none'})`);
      await p.setViewportSize({ width: 1280, height: 720 });
      const d2 = await draft(p);
      ok(!/Alfa Pip/.test(d2) && JSON.stringify(JSON.parse(d2 || '{}').wallet) === JSON.stringify(wallet1), 'the fresh draft has nothing of A and keeps the wallet');
      await p.reload(); await ready(p);                                        // L4: a reload between Make new and Snap in
      ok(!!(JSON.parse(await draft(p) || '{}').swimming || {}).id, 'the swim home that the next join waits for is kept in the draft across a reload');
      await act(p, 'g:build'); await setName(p, 'Bravo Pip');
      await doorAndAgree(p, false);
      const inB = await waitIn(p), st = await p.evaluate(() => SnapRoom.status().fighter && SnapRoom.status().fighter.name);
      let gone = false; for (let i = 0; i < 30 && !gone; i++) { gone = !(await inRing('Alfa Pip')); if (!gone) await sleep(500); }
      if (!inB) console.log('  status:', JSON.stringify(await p.evaluate(() => { const s = SnapRoom.status(); return { phase: s.phase, step: s.step, error: s.error }; })));
      if (!inB) console.log('  guide says:', (await text(p)).replace(/\s+/g, ' ').slice(0, 400), '| room:', JSON.stringify(await states()));
      ok(inB && st === 'Bravo Pip' && await inRing('Bravo Pip') && gone, `B (Bravo Pip) is in the ring and the guide follows it (${st}); browser-driven A swam home (${gone})`);
    }
    ok(await ls(p, KEYSTORE) === FAKE_KEY && await ls(p, 'trenchie.snapin.cap') === '0.5' && await ls(p, 'selected-wallet') === 'case-wallet-marker', 'the AI key, the cap and the wallet library\'s key survive the reset');

    // ---------------------------------------------------------------- 3. an agent-driven trenchie stays beside a new one
    // a second returning browser, as Pat's: its draft carries the name its agent session snapped in with (Bob)
    const snap = (...a) => { try { return execFileSync('python3', ['-I', path.join(REPO, 'near/arena/snap.py'), '--url', arenaUrl, '--state', path.join(agentDir, 'state.json'), ...a], { cwd: agentDir, timeout: 120000, stdio: ['ignore', 'pipe', 'pipe'] }).toString(); } catch (e) { return 'ERR ' + String(e.stdout || '') + String(e.stderr || e.message).slice(0, 300); } };
    const ctx2 = await chromium.launchPersistentContext(path.join(TMP, 'profile2'), { args: ['--single-process', '--no-zygote'] }); await fakeProvider(ctx2);
    let q = await ctx2.newPage(); q.on('pageerror', (e) => errs.push(e.message));
    await q.goto(guide + '?step=wallet'); await ready(q); await act(q, 'g:wallet:dev-throwaway'); await act(q, 'g:build'); await setName(q, 'Agent Pip');
    await q.close();
    // every join in this case comes from 127.0.0.1, and the host allows 5 join attempts a minute per address
    // (room/service.py join_attempts_per_minute): let visits 1 and 2's window pass, as separate players never share one
    await sleep(61000);
    const joined = snap('join', '--name', 'Agent Pip', '--preset', 'hunter-lunge', '--accept-terms', '1');
    ok(await inRing('Agent Pip'), `an agent session snapped in Agent Pip (${joined.split('\n')[0].slice(0, 100)})`);
    q = await ctx2.newPage(); q.on('pageerror', (e) => errs.push(e.message));
    await q.goto(guide + '?step=wallet'); await ready(q);
    const t3 = await text(q);
    ok(!!(await q.$('[data-act="new-trenchie"]')) && /Agent Pip/.test(t3), 'the guide\'s first screen names the saved trenchie (Agent Pip) and offers "Make a new trenchie"');
    if (await q.$('[data-act="new-trenchie"]')) {
      await act(q, 'new-trenchie'); await act(q, 'new-trenchie-yes'); await q.waitForFunction(() => Snapin.view.step === 'presets', null, { timeout: 20000 }).catch(() => {});
      ok(await q.evaluate(() => Snapin.state.name) === '' && !/Agent Pip/.test(await draft(q)), 'the new draft has no name and nothing of Agent Pip');
      await act(q, 'g:build'); await setName(q, 'Charlie Pip');
      await doorAndAgree(q, true);
      const inC = await waitIn(q), st = await q.evaluate(() => SnapRoom.status().fighter && SnapRoom.status().fighter.name);
      ok(inC && st === 'Charlie Pip' && await inRing('Charlie Pip') && await inRing('Agent Pip'), `both are in the ring: the agent's Agent Pip and the guide's Charlie Pip; the guide follows ${st}`);
    }
    snap('stop');
    // The reported repro: close every tab, the seat ends (~30 s lease), come back: the draft is kept through any reload.
    // Bravo's tab (profile 1) closes too, so no DEV trenchie is left and the host holds the next join for the unread result.
    await q.close(); await p.close();
    let out = false; for (let i = 0; i < 60 && !out; i++) { out = !(await inRing('Charlie Pip')); if (!out) await sleep(1000); }
    let joins2 = 0; q = await ctx2.newPage(); q.on('pageerror', (e) => errs.push(e.message));
    q.on('request', (r) => { if (/\/dev\/identity|\/room\/join/.test(r.url())) joins2++; });
    for (let v = 0; v < 3; v++) {
      if (v === 0) await q.goto(guide + '?step=wallet'); else await q.reload();
      await ready(q); await q.waitForFunction(() => /out of the arena/.test(document.querySelector('#app').innerText), null, { timeout: 20000 }).catch(() => {});
      const tc = (await text(q)).replace(/\s+/g, ' '), dc = JSON.parse(await draft(q) || '{}');
      ok(out && dc.name === 'Charlie Pip' && /DEV Charlie Pip is out of the arena \(no page was open to keep it\)\. Your Trenchie is kept\./.test(tc) && !!(await q.$('[data-act="rejoin"]')) && !!(await q.$('[data-act="new-trenchie"]')) && joins2 === 0,
        `closed every tab, came back${v ? ' and reloaded ' + v + 'x' : ''}: the draft still holds Charlie Pip, the guide offers "Snap Charlie Pip back in" or "Make a new trenchie", no join sent (${joins2})`);
    }
    // The lapsed seat's round result is unread, and the host holds new joins until it is read. "Snap
    // Charlie Pip back in" reads and keeps it itself (or counts the host's wait down) and never shows an agent's command.
    const seen = []; const tick = setInterval(() => { q.evaluate(() => document.querySelector('#app').innerText).then((t) => seen.push(t), () => {}); }, 500);
    await act(q, 'rejoin');
    const rejoined = await waitIn(q, 210000); clearInterval(tick);   // the host's grace for an unread result is 180 s
    if (!rejoined) console.log('  the rejoin ended:', JSON.stringify(await q.evaluate(() => { const s = SnapRoom.status(); return { phase: s.phase, step: s.step, message: s.message, error: s.error }; })));
    const cmd = seen.some((t) => /snap\.py|`/.test(t)), keptResult = await q.evaluate(() => (SnapRoom.status().notes || []).some((n) => /kept the last round/.test(n.text)));
    ok(rejoined && await inRing('Charlie Pip') && !cmd, `"Snap Charlie Pip back in" after the lapsed seat puts it back in the ring, with no command shown (${rejoined ? 'in' : await phase(q)}; waits seen: ${[...new Set(seen.map((t) => (t.match(/Back in the ring in \d+ s|Reading the last round[^\n]*/) || [''])[0]).filter(Boolean))].slice(0, 3).join(', ') || 'none'})`);
    const counted = seen.some((t) => /Back in the ring in \d+ s/.test(t));
    // the guide reads and keeps the result when the host has one to give; while the round's result is still pending it
    // cannot, and the host's own countdown is the way back in
    ok(keptResult || (rejoined && counted), `the guide read the lapsed round's result and kept it before rejoining, or (not readable yet) counted the host's wait down (kept: ${keptResult}, countdown: ${counted})`);
    await ctx2.close();

    // ---------------------------------------------------------------- 4. the DEV arena restarts while the guide is closed
    await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
    arena.child.done = true; arena.child.kill(); await sleep(1500);
    arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
    let joins = 0; p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(e.message));
    p.on('request', (r) => { if (/\/dev\/identity|\/room\/join/.test(r.url())) joins++; });
    await p.goto(guide + '?step=ring&from=arena'); await ready(p);
    for (let v = 0; v < 2; v++) {
      if (v) { await p.reload(); await ready(p); }
      await p.waitForFunction(() => /out of the arena/.test(document.querySelector('#app').innerText), null, { timeout: 20000 }).catch(() => {});
      const t4 = (await text(p)).replace(/\s+/g, ' '), d4 = JSON.parse(await draft(p) || '{}');
      ok(/DEV Bravo Pip is out of the arena/.test(t4) && /the arena restarted/.test(t4) && d4.name === 'Bravo Pip' && !!(await p.$('[data-act="rejoin"]')) && !!(await p.$('[data-act="new-trenchie"]')) && joins === 0 && await phase(p) !== 'in',
        `after the restart${v ? ' and a reload' : ''}: "Snap Bravo Pip back in" or "Make a new trenchie", the draft kept, no retry (joins ${joins}, phase ${await phase(p)})`);
    }
    await act(p, 'rejoin');
    ok(await waitIn(p) && await inRing('Bravo Pip') && !JSON.parse(await draft(p) || '{}').ended, '"Snap Bravo Pip back in" puts the same trenchie back in the ring');
    ok(await ls(p, KEYSTORE) === FAKE_KEY && await ls(p, 'trenchie.snapin.cap') === '0.5' && !!JSON.parse(await draft(p) || '{}').wallet, 'the wallet, the AI key and the cap are still there at the end');
    ok(errs.length === 0, 'no page errors in the returning browser' + (errs.length ? ': ' + errs.join(' | ') : ''));
    await ctx.close(); ctx = null;

    // ---------------------------------------------------------------- 5. a private window: storage partly blocked
    b2 = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
    const pc = await b2.newContext(); await fakeProvider(pc);
    const block = 'try{Object.defineProperty(self,"indexedDB",{get:function(){throw new DOMException("blocked","SecurityError");}});}catch(e){}';
    await pc.route('**/web/snapin/room.js', async (r) => { const res = await r.fetch(); r.fulfill({ response: res, body: block + '\n' + (await res.text()) }); });   // the worker too
    await pc.addInitScript(() => {
      try { Object.defineProperty(window, 'indexedDB', { get: function () { throw new DOMException('blocked', 'SecurityError'); } }); } catch (e) { /* */ }
      const S = Storage.prototype; S.setItem = function () { throw new DOMException('The quota has been exceeded.', 'QuotaExceededError'); };
    });
    const pp = await pc.newPage(); const perr = []; pp.on('pageerror', (e) => perr.push(e.message));
    await pp.goto(guide + '?step=wallet'); await ready(pp);
    await act(pp, 'g:wallet:dev-throwaway'); await act(pp, 'g:build'); await setName(pp, 'Delta Pip');
    await doorAndAgree(pp, true);
    ok(await waitIn(pp) && await inRing('Delta Pip'), `private window (IndexedDB missing, storage writes refused): wallet to snapped in (${await phase(pp)}; ${(await text(pp)).split('\n').slice(0, 2).join(' / ')})`);
    ok(perr.length === 0, 'no page errors in the private window' + (perr.length ? ': ' + perr.join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.stack || e).slice(0, 500)); }
  if (ctx) await ctx.close().catch(() => {});
  if (b2) await b2.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.done = true; arena.child.kill(); web.child.kill();
  fs.rmSync(TMP, { recursive: true, force: true });
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
