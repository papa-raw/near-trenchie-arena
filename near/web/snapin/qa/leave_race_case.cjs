// A review finding on d6c6490: after "Leave the arena" the page showed "swam home … Snap in" while SnapRoom.status() still
// said "in". Cause: room.js's keeper loop set the phase back to 'in' after every tick, so a tick that was in flight during a
// leave (or that landed after the session ended) undid 'leaving' / 'ended'. This case keeps a tick in flight on purpose
// (the private-notice read, delayed 2.5 s by the case) and leaves through the guide's own button, on the real DEV arena:
// once 'leaving' starts no phase may go back to 'in'; the client ends 'ended'; the page shows "left the ring" with
// "Snap in again", agreeing with the client.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/leave_race_case.cjs
'use strict';
const { spawn } = require('child_process'), path = require('path');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const ctx = await b.newContext(); const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  try {
    await p.goto(base + '/web/snapin/index.html?step=wallet'); await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
    const joined = await p.evaluate(async () => { try { await SnapRoom.join({ name: 'leavepip', preset: 'survivor-beam', termsVersion: '1' }); return SnapRoom.status().phase; } catch (e) { return 'ERR ' + e.message; } });
    ok(joined === 'in', `a real DEV fighter is in the ring (${joined})`);
    await p.evaluate(() => { Snapin.view.step = 'ring'; Snapin.render(); window.__phases = []; SnapRoom.on((st) => window.__phases.push(st.phase + (st.fighter ? '' : '(no fighter)'))); });
    // keep a keeper tick in flight across the leave: each private-notice read waits 2.5 s (case-supplied delay)
    let delayed = 0;
    await ctx.route('**/room/control/private**', async (r) => { delayed++; await sleep(2500); r.continue().catch(() => {}); });
    await sleep(1200);
    await p.click('[data-act="leave"]');
    await sleep(10000);
    const res = await p.evaluate(() => ({ phases: window.__phases.slice(), now: SnapRoom.status().phase, text: document.querySelector('main').innerText }));
    const i = res.phases.findIndex((x) => /^leaving/.test(x)), after = i < 0 ? [] : res.phases.slice(i);
    ok(delayed > 0 && i >= 0 && !after.some((x) => /^in/.test(x)), `once leaving starts no phase goes back to "in" (${delayed} delayed ticks; phases from leaving: ${after.join(' → ')})`);
    ok(res.now === 'ended', `10 s after the click the client says "${res.now}"`);
    ok(/left the ring/.test(res.text) && /Snap in again/.test(res.text) && !/swam home\s*\n/.test(res.text), `and the page agrees: "${(res.text.match(/[^\n]*left the ring[^\n]*|[^\n]*swam home[^\n]*/) || [''])[0]}" with "Snap in again"`);
    await ctx.unroute('**/room/control/private**');
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
