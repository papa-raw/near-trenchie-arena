// F72/F70 copy + W23/F28 card case, in a real browser at 1440 and 390.
// 1. No placeholder anywhere a player can reach by clicking: every flow step, every workshop tab, every AI door state.
// 2. Board 1's AI step: NEAR AI Cloud's measured estimate, "Not measured yet" on the doors nobody has measured, and the plan
//    doors' weekly stop (the older per-door cost box and its basis line are gone with the S4 key panel).
// 3. The card: with no fighter it says what it needs; with a record it draws the gauge from the predictions log lines
//    (/house/predictions.jsonl: score and base_score per life) and the bag and serials from /room/observe; under 10 scored
//    lives no needle and a plain count; a log the arena does not serve is said plainly. The log lines and the observe answer
//    for the card are supplied by this test (a DEV host with the house log route is another lane's, not merged here);
//    the needle's side is computed from them and checked.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/copy_card_case.cjs [out-dir]
'use strict';
const { spawn } = require('child_process'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..'), OUT = process.argv[2] || path.join(os.tmpdir(), 'snapin-copy-card');
fs.mkdirSync(OUT, { recursive: true });
let pass = 0, fail = 0; const report = [];
const ok = (c, m) => { report.push((c ? 'PASS ' : 'FAIL ') + m); if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PLACEHOLDER = /After model test|Design only|not enforced|Count pending|Art pending|art pending|Preview state|would hold|Proposed key|Not available yet|\bTBD\b|lorem|coming soon/i;
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
const row = (id, i, actual, score, base) => ({ actual, base_score: base, batch_tx: null, life: 'dev-local-r1/' + id + ':life:' + i, lock_hash: 'x', model: 'test', owner: id + '.local', persona: id, prediction: true, returned_yocto: '0', rules_hash: 'x', score, spread_pct: [40, 30, 20, 10], stake_yocto: '0', zero_pct: 10 });

(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const ctx = await b.newContext();
  const p = await ctx.newPage(); const errs = [];
  p.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.text().slice(0, 200) + ' @ ' + p.url().replace(base, '')); });
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
    p.on('response', (r) => { if (r.status() >= 400 && !/cloud-api\.near\.ai/.test(r.url())) errs.push('http ' + r.status() + ' ' + r.url().replace(/^https?:\/\/[^/]+/, '')); });
  const ready = () => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
  const click = async (act) => { await p.click(`[data-act="${act}"]`); await sleep(200); };
  const seen = [];
  const sweep = async (where) => { const t = await p.innerText('body'); const hit = t.match(PLACEHOLDER); seen.push([where, hit ? hit[0] : null]); return t; };
  try {
    for (const W of [1440, 390]) {
      await p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
      await p.goto(base + '/web/snapin/index.html?step=wallet'); await ready(); await p.evaluate(() => { localStorage.clear(); sessionStorage.clear(); }); await p.reload(); await ready();
      // ---- board 1's guide, by clicks (each state's exact copy is board1_guide_case.cjs's; here: no placeholder anywhere)
      await sweep(`${W} wallet`); await click('g:wallet:dev-throwaway'); await sweep(`${W} fighter`);
      await click('g:build'); await sleep(400); await sweep(`${W} personality`);
      await click('g:step:doors'); await sweep(`${W} AI doors`);
      // ---- each AI door and its cost line (board 1: estimated and labelled; "Not measured yet" until someone measures)
      const doorCost = {};
      for (const door of ['NEAR AI Cloud', 'Claude', 'OpenRouter']) {
        await click('g:door:key:' + door); doorCost[door] = await sweep(`${W} ${door} key`);
        if (W === 1440) await p.screenshot({ path: path.join(OUT, `door-${door.replace(/\W+/g, '-')}-${W}.png`), fullPage: true });
        await click('g:other');
      }
      for (const door of ['Claude Code', 'Codex']) { await click('g:door:plan:' + door); await sleep(800); doorCost[door] = await sweep(`${W} ${door} plan`); await click('g:other'); }
      ok(/About \$0\.10 an hour in a busy fight\. At the cap, your trenchie fights on its own tactics until the hour ends\./.test(doorCost['NEAR AI Cloud']),
        `${W}: NEAR AI Cloud's key screen shows the measured estimate in board 1's words ("About $0.10 an hour in a busy fight.")`);
      ok(['Claude', 'OpenRouter'].every((d) => /Not measured yet for this AI\. Start with a low cap\./.test(doorCost[d])),
        `${W}: Claude and OpenRouter say "Not measured yet for this AI. Start with a low cap." (no unmeasured number shown)`);
      ok(['Claude Code', 'Codex'].every((d) => /Your session’s own stop: it stops giving orders at this share of your plan’s week\./.test(doorCost[d])),
        `${W}: the plan doors name the session's own weekly stop and say "not reported" when it cannot report`);
      // ---- terms, ring, workshop tabs
      await p.goto(base + '/web/snapin/index.html?step=agree'); await ready(); await sleep(800); await sweep(`${W} agree`);
      for (const tab of ['battle', 'inventory', 'look', 'persona', 'card', 'agree', 'respawn']) { await p.goto(base + '/web/snapin/index.html?mode=workshop&tab=' + tab); await ready(); await sleep(400); await sweep(`${W} workshop ${tab}`); }
      // ---- the card
      await p.goto(base + '/web/snapin/index.html?mode=workshop&tab=card'); await ready();
      ok(/Snap in to give the card a record/.test(await p.innerText('main')), `${W}: with no fighter the card says what it needs and offers Snap in`);
      // a fighter for the card (test-supplied: the page's client is told it drives dev-cardpip; no join in this case)
      await p.evaluate(() => { SnapRoom.status = () => ({ phase: 'in', fighter: { id: 'dev-cardpip', name: 'Cardpip', lives: 1 } }); Snapin.render(); });
      const serve = async (rows, status) => { await p.unroute('**/house/predictions.jsonl').catch(() => {}); await p.route('**/house/predictions.jsonl', (r) => r.fulfill({ status: status || 200, contentType: 'application/x-ndjson', headers: { 'X-Log-Hash': 'abc123def4567890' }, body: status ? 'not found' : rows.map((x) => JSON.stringify(x)).join('\n') + '\n' })); };
      await p.route('**/room/observe', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ fighters: [{ fighter_id: 'dev-cardpip', equipped: [{ slot: 'weapon', item_id: 'c-zap', serial_id: null, tier: 'common' }, { slot: 'head', item_id: 'st-cap', serial_id: null, tier: 'common' }, { slot: 'body', item_id: 'st-tee', serial_id: null, tier: 'common' }, { slot: 'trinket', item_id: 'leg-builder-census', serial_id: 'leg-builder-census:2', tier: 'legendary' }] }] }) }));
      // three lives: a count, no needle
      await serve([row('dev-cardpip', 0, 1, 115000, 58572), row('dev-cardpip', 1, 0, 365000, 108072), row('dev-cardpip', 2, 2, 90000, 120000), row('someone-else', 0, 3, 1000, 9000)]);
      await click('card-refresh'); await sleep(1500);
      let t = await p.innerText('main'), svg = await p.$eval('.persona-card svg', (e) => e.textContent);
      ok(/needs 10 scored lives; your AI has 3/.test(t) && /Lives 3 · KOs 3/.test(svg) && /Mean score 0\.19 \(0 = spot on\) · 3 lives/.test(svg) && !(await p.$('.persona-card svg path[stroke-width="3.4"]')), `${W}: 3 scored lives: a count, no needle, the record and mean score from the log ("${(svg.match(/Mean score[^·]*· \d+ lives/) || [''])[0]}"), other AIs' lines ignored`);
      ok(/Driftwood Bonk|Jelly Zapper/.test(svg) && /#2/.test(svg), `${W}: the bag and the legendary's serial come from what the fighter wears (/room/observe)`);
      if (W === 1440) await p.screenshot({ path: path.join(OUT, `card-3-lives-${W}.png`), fullPage: true });
      // twelve lives, scores well under the base rate: the needle leans careful
      const good = Array.from({ length: 12 }, (_, i) => row('dev-cardpip', i, i % 3, 60000, 120000));
      await serve(good); await click('card-refresh'); await sleep(1500);
      const needle = await p.$eval('.persona-card svg path[stroke-width="3.4"]', (e) => e.getAttribute('d')).catch(() => null);
      const nx = needle ? Number(needle.split('L')[1].split(' ')[0]) : null;
      ok(needle && nx > 170, `${W}: 12 scored lives at half the base rate's score: the needle leans careful (tip x ${nx}, centre 170; expected position 0.75)`);
      if (W === 1440) await p.screenshot({ path: path.join(OUT, `card-12-lives-${W}.png`), fullPage: true });
      // twelve lives worse than the base rate: reckless
      const bad = Array.from({ length: 12 }, (_, i) => row('dev-cardpip', i, i % 3, 180000, 120000));
      await serve(bad); await click('card-refresh'); await sleep(1500);
      const needle2 = await p.$eval('.persona-card svg path[stroke-width="3.4"]', (e) => e.getAttribute('d')).catch(() => null), nx2 = needle2 ? Number(needle2.split('L')[1].split(' ')[0]) : null;
      ok(needle2 && nx2 < 170, `${W}: 12 scored lives worse than the base rate: the needle leans reckless (tip x ${nx2})`);
      // a log the arena does not serve
      await serve([], 404); await click('card-refresh'); await sleep(1500);
      ok(/Record unavailable, retrying: this arena serves no predictions log\. The gauge stays empty until it can be read\./.test(await p.innerText('main')), `${W}: no log route: said plainly, gauge empty`);
      await p.unroute('**/room/observe'); await p.unroute('**/house/predictions.jsonl');
      await p.reload(); await ready();   // drops the stub
    }
    const hits = seen.filter((x) => x[1]);
    ok(seen.length > 30 && hits.length === 0, `no placeholder phrase on ${seen.length} screens reached by clicks` + (hits.length ? ': ' + JSON.stringify(hits.slice(0, 5)) : ''));
    const own = errs.filter((e) => !/status of 404/.test(e) && !/^http 404 \/house\/predictions\.jsonl/.test(e));   // only the test-supplied missing log
    ok(own.length === 0, 'console clean (set aside: the 404 of the test-supplied missing log)' + (own.length ? ': ' + own.slice(0, 4).join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 400)); try { await p.screenshot({ path: path.join(OUT, 'crash.png'), fullPage: true }); } catch (e2) { /* gone */ } }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  fs.writeFileSync(path.join(OUT, 'copy-card-case.json'), JSON.stringify({ pass, fail, at: new Date().toISOString(), screens: seen, report }, null, 1));
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed; frames in ${OUT}`);
  process.exit(fail ? 1 : 0);
})();
