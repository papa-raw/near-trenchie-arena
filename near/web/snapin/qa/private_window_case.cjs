// Pat's click-through item 39 (2026-11-12): "incognito mode really fucked up the game". The guide and the arena page in a
// private window, on the real DEV arena, in two storage modes:
//   incognito : a fresh off-the-record Chromium context (Playwright's newContext is Chrome's incognito profile) with
//               third-party cookies blocked (--test-third-party-cookie-phaseout), storage as incognito gives it;
//   blocked   : the same, with localStorage, sessionStorage and indexedDB throwing SecurityError on access, in the page
//               and in the guide's worker (Chrome with "Block all cookies", or a hardened private window).
// Each mode: the guide from the wallet to snapped in through its own screens, then "Watch your trenchie" opens the arena
// page, which must show the live arena and either keep driving the trenchie (incognito) or say it cannot (blocked); no page
// errors anywhere. The NEAR AI Cloud "Say hi" is answered by the case (no key, no spend). Not covered here: a real wallet's
// sign-in in its own frame or pop-up (Meteor), and real Chrome's own incognito window (this lane's sandbox cannot start
// Chrome; the reviewer's reader pass runs that one).
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/private_window_case.cjs
'use strict';
const { spawn } = require('child_process'), path = require('path');
const { chromium } = require('playwright');
const G = require('./board1_flow.cjs');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
const BLOCK = 'for (const k of ["localStorage", "sessionStorage", "indexedDB"]) { try { Object.defineProperty(self, k, { get() { throw new DOMException("The user denied permission to access the database.", "SecurityError"); } }); } catch (e) { /* */ } }';
const act = async (p, a) => { await p.click(`[data-act="${a}"]`); await sleep(250); };
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  // in the arena in any state (a KO'd or respawning trenchie is still this player's, in the arena)
  const inRing = async (name) => { try { const o = await (await fetch(arenaUrl + '/room/observe')).json(); return (o.fighters || []).some((f) => String(f.public_name).indexOf('DEV ' + name) === 0); } catch (e) { return false; } };
  let b = null;
  try {
    for (const [mode, name] of [['incognito', 'Echo Pip'], ['blocked', 'Foxtrot Pip']]) {
      // one browser per mode: this lane's sandbox runs Chromium only as --single-process, which holds one context
      b = await chromium.launch({ args: ['--single-process', '--no-zygote', '--test-third-party-cookie-phaseout'] });
      const ctx = await b.newContext(), errs = [];
      await ctx.route('https://cloud-api.near.ai/**', (r) => r.request().method() === 'OPTIONS'
        ? r.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'POST' } })
        : r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ choices: [{ message: { content: 'hi' } }] }) }));
      if (mode === 'blocked') {
        await ctx.addInitScript(BLOCK);
        await ctx.route('**/web/snapin/room.js', async (r) => { const res = await r.fetch(); r.fulfill({ response: res, body: BLOCK + '\n' + (await res.text()) }); });   // the worker too
      }
      const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push('guide: ' + e.message));
      // through board 1's guide, in one page load (with storage blocked a reload would lose the draft); Snap in lands on the
      // arena page's panel when this browser keeps the session, and stays on the guide when it cannot (item 39)
      const where = await G.snapIn(p, { url: base + '/web/snapin/index.html', name: name, preset: 'Survivor Beam', key: 'sk-case-not-a-real-key', backToGuide: false }).catch((e) => 'failed: ' + e.message);
      p.on('pageerror', (e) => errs.push('page: ' + e.message));
      ok(where === (mode === 'incognito' ? 'arena' : 'guide') && await inRing(name), `${mode}: wallet to snapped in through the guide; Snap in lands on ${where} (${name} in the arena)`);
      if (mode === 'incognito') {
        await sleep(6000);
        const pan = await p.evaluate(() => { const e = document.getElementById('b1-panel'); return e && !e.hidden ? e.innerText.replace(/\s+/g, ' ') : ''; }).catch(() => '');
        const live = await p.evaluate(() => !!document.querySelector('#stage') && document.querySelector('#stage').width > 0).catch(() => false);
        ok(live && pan.includes(name) && await inRing(name), `${mode}: the arena page shows the live arena and the trenchie's own panel, and keeps driving it ("${pan.slice(0, 80)}")`);
      } else {
        const ring = (await p.evaluate(() => document.querySelector('#app').innerText)).replace(/\s+/g, ' ');
        ok(/This browser keeps your Trenchie only on this page \(it cannot store the key\): closing this page sends your Trenchie home\./.test(ring) && !(await p.$('[data-act="watch-mine"]')),
          `${mode}: the guide keeps the trenchie, says it is kept only on this page, and offers no page move that would lose it`);
        await sleep(40000);   // longer than the 30 s lease: still in, because this page keeps renewing it
        ok(await inRing(name) && await p.evaluate(() => SnapRoom.status().phase) === 'in', `${mode}: 40 s later the trenchie is still in the arena (the old move to the arena page lost it: item 39's one real failure)`);
      }
      ok(errs.length === 0, `${mode}: no page errors` + (errs.length ? ': ' + errs.slice(0, 4).join(' | ') : ''));
      await ctx.close(); await b.close(); b = null;
    }
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.stack || e).slice(0, 400)); }
  if (b) await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
