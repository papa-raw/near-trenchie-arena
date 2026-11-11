// Three review findings on d798dbe, in a real browser:
//  1. a predictions log that stays down is asked again with a back-off (4 s, 8, 16, … capped at 60), not every 4 s;
//  2. at 390 every Agree tick box keeps its 24 px beside a long label;
//  3. the ring view's text buttons are at least 44 px tall (a thumb-sized target) at 1440 and 390.
// The fighter on the ring view and the card's log are supplied by this case (labelled); the pages are the real guide on a
// real DEV arena (snap_local.py through serve.py).
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/low_fix_case.cjs
'use strict';
const { spawn } = require('child_process'), path = require('path');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function start(args, ready) {
  const child = spawn('python3', ['-B', ...args], { cwd: REPO, stdio: ['ignore', 'pipe', 'pipe'] });
  return new Promise((resolve, reject) => {
    let out = ''; const t = setTimeout(() => reject(new Error('no start line: ' + out.slice(0, 300))), 30000);
    const on = (d) => { out += d; const m = ready(out); if (m) { clearTimeout(t); resolve({ child, m }); } };
    child.stdout.on('data', on); child.stderr.on('data', (d) => { out += d; });
    child.on('exit', (c) => reject(new Error('exited ' + c + ': ' + out.slice(0, 300))));
  });
}
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const p = await (await b.newContext()).newPage();
  const ready = () => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
  try {
    // ---- 2. the Agree tick boxes at 390
    await p.setViewportSize({ width: 390, height: 844 });
    await p.goto(base + '/web/snapin/index.html?step=wallet'); await ready();
    await p.evaluate(() => { const P = JSON.parse(localStorage.getItem('trenchie.snapin.v1') || '{}'); P.wallet = { id: 'dev-throwaway', accountId: 'a'.repeat(64), network: 'testnet' }; localStorage.setItem('trenchie.snapin.v1', JSON.stringify(P)); });
    await p.goto(base + '/web/snapin/index.html?step=agree'); await ready();
    await p.waitForFunction(() => document.querySelectorAll('.checks input').length === 3, null, { timeout: 20000 });
    const boxes = await p.$$eval('.checks input', (els) => els.map((e) => Math.round(e.getBoundingClientRect().width * 10) / 10));
    ok(boxes.every((w) => w >= 24), `at 390 every Agree tick box is at least 24 px wide (${boxes.join(', ')})`);
    // ---- 3. the ring view's text buttons (a fighter in the ring, case-supplied)
    for (const W of [1440, 390]) {
      await p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
      await p.goto(base + '/web/snapin/index.html?step=agree'); await ready();
      await p.evaluate(() => { SnapRoom.status = () => ({ phase: 'in', step: 'ring', message: '', fighter: { id: 'dev-lowpip', name: 'Lowpip', lives: 1, lastPick: { state: 'accepted' } } }); Snapin.view.step = 'ring'; Snapin.render(); });
      await sleep(400);
      const links = await p.$$eval('main button.textlink', (els) => els.map((e) => e.textContent.trim() + ':' + Math.round(e.getBoundingClientRect().height)));
      ok(links.length >= 2 && links.every((x) => Number(x.split(':').pop()) >= 44), `${W}: the ring view's text buttons are at least 44 px tall (${links.join(', ')})`);
    }
    // ---- 1. the back-off on a log that stays down
    await p.setViewportSize({ width: 1440, height: 900 });
    let asks = [];
    await p.route('**/house/predictions.jsonl', (r) => { asks.push(Date.now()); r.fulfill({ status: 503, contentType: 'text/plain', body: 'down' }); });
    await p.route('**/room/observe', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{"fighters":[]}' }));
    await p.goto(base + '/web/snapin/index.html?mode=workshop&tab=battle'); await ready();
    await p.evaluate(() => { SnapRoom.status = () => ({ phase: 'in', fighter: { id: 'dev-lowpip', name: 'Lowpip', lives: 1 } }); });
    asks = []; await p.click('[data-act="tab:card"]'); const t0 = Date.now();
    await sleep(31000);
    const gaps = asks.slice(1).map((t, i) => Math.round((t - asks[i]) / 1000));
    ok(asks.length >= 3 && asks.length <= 5 && gaps.every((g, i) => i === 0 || g >= gaps[i - 1]), `a log that stays down is asked ${asks.length} times in 31 s with growing gaps (${gaps.join(' s, ')} s), not every 4 s`);
    ok(/Record unavailable, retrying/.test(await p.innerText('main')), 'and the card still says "Record unavailable, retrying"');
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
