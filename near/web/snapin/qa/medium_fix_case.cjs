// Two review findings on 8a96a77, in a real browser:
//  1. the card never claims zero lives when the predictions log cannot be read: it says "Record unavailable, retrying", and
//     it does retry: once the log answers, the record appears with no click;
//  2. the AI step's spend line reads the cap the player saved, even before the player's AI has stepped into the ring
//     (its capUsd is still null then).
// The fighter, the log and the player AI's status are supplied by this case (labelled); the pages are the real guide.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/medium_fix_case.cjs [out-dir]
'use strict';
const { spawn } = require('child_process'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..'), OUT = process.argv[2] || path.join(os.tmpdir(), 'snapin-medium-fix');
fs.mkdirSync(OUT, { recursive: true });
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
const row = (i, actual) => ({ actual, base_score: 120000, life: 'dev-local-r1/dev-medpip:life:' + i, persona: 'dev-medpip', prediction: true, score: 90000, spread_pct: [40, 30, 20, 10], zero_pct: 10 });

(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const ctx = await b.newContext();
  // a player AI that has not stepped into the ring yet: no cap known to it (capUsd null), a little spend (case-supplied)
  // the case stands in for the player's AI (a known spend); the real brain.js (on main now) would replace it, so it is served empty, labelled
  await ctx.route('**/web/snapin/brain.js', (r) => r.fulfill({ status: 200, contentType: 'text/javascript', body: '/* medium_fix_case: brain.js withheld; the case stands in for SnapBrain */' }));
  await ctx.addInitScript(() => { window.SnapBrain = { on(fn) { fn({ state: 'off', chip: 'Your trenchie is on the arena’s own tactics.', spendHourUsd: 0.012, capUsd: null, conversation: [] }); return () => {}; } }; });
  await ctx.route('https://cloud-api.near.ai/**', (r) => r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ id: 't', object: 'chat.completion', choices: [{ index: 0, message: { role: 'assistant', content: 'Ready.' }, finish_reason: 'stop' }], usage: { prompt_tokens: 9, completion_tokens: 2 } }) }));
  const p = await ctx.newPage();
  const ready = () => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
  try {
    await p.setViewportSize({ width: 1440, height: 900 });
    // ---- 1. the card with a log that cannot be read, then can
    let logUp = false;
    await p.route('**/house/predictions.jsonl', (r) => logUp ? r.fulfill({ status: 200, contentType: 'application/x-ndjson', body: [row(0, 1), row(1, 0), row(2, 2)].map((x) => JSON.stringify(x)).join('\n') + '\n' }) : r.fulfill({ status: 503, contentType: 'text/plain', body: 'down' }));
    await p.route('**/room/observe', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ fighters: [] }) }));
    await p.goto(base + '/web/snapin/index.html?mode=workshop&tab=battle'); await ready();
    await p.evaluate(() => { SnapRoom.status = () => ({ phase: 'in', fighter: { id: 'dev-medpip', name: 'Medpip', lives: 4 } }); });
    await p.click('[data-act="tab:card"]'); await sleep(1500);
    const down = await p.evaluate(() => ({ svg: document.querySelector('.persona-card svg').textContent, note: document.querySelector('main').innerText }));
    ok(/Record unavailable, retrying/.test(down.svg) && !/No lives yet|No lives scored yet/.test(down.svg), `an unreadable record says "Record unavailable, retrying" and never "No lives yet" (card: "${(down.svg.match(/Record unavailable[^·]*|No lives[^·]*/) || [''])[0].trim()}")`);
    await p.screenshot({ path: path.join(OUT, 'card-record-unavailable.png'), fullPage: true });
    logUp = true; await sleep(6000);
    const up = await p.evaluate(() => document.querySelector('.persona-card svg').textContent);
    ok(/Lives 3 · KOs 3/.test(up) && !/Record unavailable/.test(up), 'it retries by itself: once the log answers, the record appears with no click');
    // ---- 2. the spend line reads the saved cap
    await p.evaluate(() => {
      localStorage.setItem('trenchie.snapin.cap', '0.20');
      const P = JSON.parse(localStorage.getItem('trenchie.snapin.v1') || '{}'); P.wallet = { id: 'dev-throwaway', accountId: 'a'.repeat(64), network: 'testnet' }; localStorage.setItem('trenchie.snapin.v1', JSON.stringify(P));
    });
    // the AI door's connection panel and its spend line live in the guide's stand-alone AI door (mode=login); board 1's
    // steps carry the money line on the trenchie panel instead
    await p.goto(base + '/web/snapin/index.html?mode=login'); await ready();
    await p.click('[data-act="ai:door:NEAR AI Cloud"]'); await sleep(200); await p.fill('#key', 'sk-test-player-key'); await p.click('[data-act="ai:test"]');
    await p.waitForFunction(() => SnapDoors.state.state === 'connected', null, { timeout: 20000 });
    await p.click('[data-act="ai:panel"]'); await sleep(300);
    const line = await p.evaluate(() => (document.querySelector('.connection-panel') || document.body).innerText);
    ok(/Spent this hour: \$0\.012 of your \$0\.20 cap\./.test(line) && !/no cap set/.test(line), `with a saved cap and an AI not yet in the ring, the spend line reads the saved cap ("${(line.match(/Spent this hour:[^\n]*/) || [''])[0]}")`);
    await p.screenshot({ path: path.join(OUT, 'spend-line-saved-cap.png'), fullPage: true });
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed; frames in ${OUT}`);
  process.exit(fail ? 1 : 0);
})();
