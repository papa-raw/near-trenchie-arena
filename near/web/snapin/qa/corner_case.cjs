// F22 + F77 case: the corner (the bench card at respawn) on the room's own data, and the five battle options through
// join and respawn, in a real browser at 1440 and 390.
// Starts its own DEV arena (snap_local.py) and serve.py. A visitor snaps in as Hunter Lunge through the guide (the provider's
// key check answered by this test, as in flow_case), opens the corner and clicks every control: the five next-life options,
// a spread that does not add up (refused, plainly), a good one, Ready next life, the disabled stake/move/lock (nothing
// happens, the reason is printed), reload and Back. It then waits for a real KO: the next life must be filed, signed,
// as Brawler Zap and the fighter must wear Brawler Zap's kit (from presets.py on the live rules). With the arena stopped the
// corner says so. Last, the Persona tab saves one sheet per battle option and check_personas.py must print "5/5 valid".
// The page reads /dev/corner every second; the case's own reads carry an x-case-read header. The corner's state check waits
// for the page's poll to show the state the case just read (a one-poll race, wider under load).
// CORNER_FORCE_STALE_MS=N (default 0, off) forces that race: for N ms after the corner opens, the page's own polls are
// answered as a poll taken just before the fighter entered the ring (state bench, no respawn time); the case's reads are not.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/corner_case.cjs [out-dir]
'use strict';
const { spawn, execFileSync } = require('child_process'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const NEAR = path.resolve(__dirname, '..', '..', '..'), REPO = path.dirname(NEAR);
const OUT = process.argv[2] || path.join(os.tmpdir(), 'snapin-corner');
const FORCE_STALE_MS = Number(process.env.CORNER_FORCE_STALE_MS) || 0;
fs.mkdirSync(OUT, { recursive: true });
let pass = 0, fail = 0; const report = [];
const ok = (c, m) => { report.push((c ? 'PASS ' : 'FAIL ') + m); if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs'), G = require('./board1_flow.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
// the five kits on the live rules table, from the arena's own code
const KITS = JSON.parse(execFileSync('python3', ['-B', '-c', "import sys,json; sys.path[:0]=['near/arena']; import presets, sim; print(json.dumps({p['name']: p['loadout'] for p in presets.all_presets(sim.DEFAULT_RULES)}))"], { cwd: REPO }).toString());

(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m, ws = 'ws://127.0.0.1:' + port;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const ctx = await b.newContext({ acceptDownloads: true });
  await ctx.route('https://cloud-api.near.ai/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ id: 'test', object: 'chat.completion', choices: [{ index: 0, message: { role: 'assistant', content: 'Ready.' }, finish_reason: 'stop' }], usage: { prompt_tokens: 9, completion_tokens: 2 } }) }));
  let staleUntil = 0, staleServed = 0;
  if (FORCE_STALE_MS) await ctx.route('**/dev/corner?**', async (route) => {
    if (route.request().headers()['x-case-read'] || Date.now() > staleUntil) return route.continue();
    const r = await route.fetch(), j = await r.json(); j.state = 'bench'; delete j.respawn_at_ms; staleServed++;
    return route.fulfill({ response: r, body: JSON.stringify(j) });
  });
  const p = await ctx.newPage(); const errs = [], failed = [];
  p.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.type() + ': ' + m.text().slice(0, 240) + ' @ ' + p.url().replace(base, '')); });
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
    p.on('response', (r) => { if (r.status() >= 400 && !/cloud-api\.near\.ai/.test(r.url())) errs.push('http ' + r.status() + ' ' + r.url().replace(/^https?:\/\/[^/]+/, '')); });
  p.on('requestfailed', (r) => failed.push(r.url()));
  const frames = [];
  const view = async (W) => p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
  const shot = async (name, W) => { const f = `${String(frames.length + 1).padStart(2, '0')}-${name}-${W}.png`; await p.screenshot({ path: path.join(OUT, f), fullPage: true, timeout: 30000 }); frames.push(f); };
  const ready = () => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
  const click = async (act) => { await p.click(`[data-act="${act}"]`); await sleep(150); };
  const status = () => p.evaluate(() => SnapRoom.status());
  const corner = () => p.evaluate(() => fetch('/dev/corner?fighter=' + encodeURIComponent(SnapRoom.status().fighter.id), { headers: { 'x-case-read': '1' } }).then((r) => r.json()));
  const wide = async (W) => { const x = await p.evaluate(() => document.documentElement.scrollWidth); return x <= W; };
  try {
    await view(1440);
    // ---- snap in through the guide, as Hunter Lunge
    await p.goto(base + '/web/snapin/index.html?step=wallet&ws=' + encodeURIComponent(ws)); await ready();
    // snap in through board 1's guide (a cap to snap in, Pat's Q2; then none again: this case's own steps set one where it needs it)
    await G.snapIn(p, { skipGoto: true, name: 'Cornerpip', preset: 'Hunter Lunge', claim: true, key: 'sk-test-player-key', clearCapAfter: true });
    await p.waitForFunction(() => SnapRoom.status().phase === 'in', null, { timeout: 90000 });
    let st = await status();
    ok(st.fighter.preset === 'hunter-lunge' && st.fighter.lastPick && st.fighter.lastPick.state === 'none', `in the ring as ${st.fighter.id}, battle option ${st.fighter.preset}, first life filed with no prediction (the guide picks no level for the player), first life's pick ${st.fighter.lastPick && st.fighter.lastPick.state}`);
    const obs0 = await p.evaluate(() => fetch('/room/observe').then((r) => r.json()));
    const me0 = obs0.fighters.find((f) => f.fighter_id === st.fighter.id), w0 = me0 && (me0.equipped || []).find((e) => e.slot === 'weapon');
    ok(w0 && w0.item_id === KITS['Hunter Lunge'].weapon, `the first life wears Hunter Lunge's weapon (${w0 && w0.item_id}; presets.py: ${KITS['Hunter Lunge'].weapon})`);
    // ---- the corner
    if (FORCE_STALE_MS) staleUntil = Date.now() + FORCE_STALE_MS;
    await click('corner');
    await p.waitForFunction(() => /Last life|First life/.test(document.querySelector('main').innerText), null, { timeout: 20000 });
    ok(/mode=workshop/.test(p.url()) && /tab=respawn/.test(p.url()), 'the corner has its own address (mode=workshop&tab=respawn)');
    // the page shows what its last poll read, up to a second (more under load) behind a fresh read: wait for its poll to
    // catch up with the room before comparing (up to 20 s), and say how long that took
    const shows = (c, t) => new RegExp(c.state === 'ring' ? 'In the ring' : 'Respawn in|On the bench', 'i').test(t);
    let c0 = await corner(), text0 = await p.innerText('main'); const waited0 = Date.now();
    while (!shows(c0, text0) && Date.now() - waited0 < 20000) { await sleep(250); c0 = await corner(); text0 = await p.innerText('main'); }
    const shown0 = ((text0.match(/In the ring|Respawn in \d+:\d\d|On the bench/i) || ['none'])[0]);
    ok(shows(c0, text0), `the corner shows the room's state (${c0.state}, respawn_at_ms ${c0.respawn_at_ms}; the page shows "${shown0}" after ${((Date.now() - waited0) / 1000).toFixed(1)} s` + (FORCE_STALE_MS ? `; forced: ${staleServed} page polls answered stale for ${FORCE_STALE_MS} ms` : '') + ')');
    ok(/Taken last life[\s\S]*Not tracked by the arena yet/.test(text0) && /Item returns to your plot: not tracked by the arena yet/.test(text0), 'what the arena does not track, the corner says is not tracked');
    await shot('corner', 1440);
    // the five options for the next life, every one
    const acts = await p.$$eval('[data-act^="next-preset:"]', (els) => els.map((e) => e.dataset.act));
    let pressed = 0; for (const a of acts) { await click(a); if (await p.$eval(`[data-act="${a}"]`, (e) => e.getAttribute('aria-pressed') === 'true')) pressed++; }
    ok(acts.length === 5 && pressed === 5, `next life: ${pressed}/${acts.length} battle options clicked and shown as chosen`);
    await click('next-preset:brawler-zap');
    // the disabled market controls: a click does nothing, the reason is on the card
    const dis = await p.$$eval('button[disabled]', (els) => els.map((e) => e.textContent.trim()));
    ok(dis.length === 3 && /onchain market, which is not deployed yet/.test(await p.innerText('main')), `stake, move and sale lock are off with the reason printed (${dis.join(', ')})`);
    // a spread that does not add up, then a good one
    const fills = async (v, z) => { for (let k = 0; k < 4; k++) await p.fill(`[data-spread="${k}"]`, String(v[k])); await p.fill('#zero-ko', String(z)); };
    await fills([50, 30, 20, 10], 10);
    ok(/Spread totals 110% \(needs 100%\)/.test(await p.innerText('#spread-total')), 'the total updates as you type and says it needs 100%');
    await click('ready');
    ok(/add up to 110% now/.test(await p.innerText('#locked')), `Ready with 110% is refused plainly: "${await p.innerText('#locked')}"`);
    await shot('corner-refused', 1440);
    await fills([25, 25, 25, 25], 20); await click('next-preset:brawler-zap'); await click('ready');
    const saved = await p.innerText('#locked');
    ok(/Saved\. Your next life fights as Brawler Zap, predicting 25\/25\/25\/25 and 20% for zero KOs/.test(saved), `Ready next life saves it: "${saved.slice(0, 160)}"`);
    st = await status();
    ok(st.fighter.preset === 'brawler-zap', 'the keeper holds Brawler Zap for the next life');
    // a KO can land before Ready (the DEV crowd is live): lives up to this one were filed with the first pick, later ones with this
    const atReady = { lives: st.fighter.lives, life: st.fighter.life }, lifeNo = (id) => Number((String(id).match(/(\d+)$/) || [])[1]);
    // keyboard: the corner's controls take focus with a ring
    const stops = [];
    await p.focus('[data-act="next-preset:brawler-zap"]');   // from the last option, Tab walks the inputs and buttons below
    for (let i = 0; i < 8; i++) { await p.keyboard.press('Tab'); stops.push(await p.evaluate(() => { const e = document.activeElement, s = getComputedStyle(e); return (e.dataset.act || e.id || e.getAttribute('aria-label') || e.tagName) + ':' + (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2); })); }
    ok(stops.length && stops.every((x) => /:true$/.test(x)), `keyboard: Tab through the spread, zero and Ready shows a ring at each stop (${stops.join(', ')})`);
    // typing is never interrupted by the corner's polling: focus stays in a KO field across 3 s of polls
    await p.click('[data-spread="2"]'); await p.keyboard.press('End'); await sleep(3200);
    ok(await p.evaluate(() => document.activeElement && document.activeElement.dataset.spread === '2'), 'focus stays in a KO field while the corner polls the room');
    // the countdown as drawn: a down fighter with its respawn 31 s away on room time
    const drawn = await p.evaluate(() => { const C = Snapin.corner, keep = C.data; C.data = Object.assign({}, keep, { state: 'down', respawn_at_ms: C.now + Math.round(performance.now() - C.at) + 31000 }); Snapin.render(); const t = document.querySelector('main').innerText.match(/Respawn in \d+:\d\d/i); C.data = keep; Snapin.render(); return t && t[0]; });
    ok(/Respawn in 0:3[01]/i.test(drawn || ''), `a down fighter's card reads "${drawn}" (31 s on room time)`);
    // reload and Back
    await p.reload(); await ready(); await p.waitForFunction(() => /Last life|First life/.test(document.querySelector('main').innerText), null, { timeout: 20000 });
    ok(await p.evaluate(() => Snapin.view.mode === 'workshop' && Snapin.view.tab === 'respawn' && SnapRoom.status().fighter && SnapRoom.status().fighter.preset === 'brawler-zap'), 'a reload stays on the corner and keeps the next-life pick');
    await view(390); await sleep(600); await shot('corner', 390);
    ok(await wide(390), 'no sideways scroll on the corner at 390');
    await p.goBack(); await sleep(600);
    ok(await p.evaluate(() => Snapin.view.mode === 'flow' && Snapin.view.step === 'ring'), 'Back from the corner returns to the in-the-ring view');
    await shot('ring', 390);
    await p.goForward(); await sleep(600); await view(1440);
    // ---- a real KO: the next life must come in as Brawler Zap, filed signed
    const t0 = Date.now(); let down = null, next = null; const seenStates = new Set();
    while (Date.now() - t0 < 300000) {
      st = await status();
      const c = await corner().catch(() => null);
      if (c) { seenStates.add(c.state + (c.respawn_at_ms ? '+timer' : '') + ((c.pending || []).length ? '+' + c.pending.map((x) => x.kind).join('/') : '')); }
      if (c && c.respawn_at_ms && !down) {
        down = c;
        down.page = await p.waitForFunction(() => /Respawn in \d+:\d\d/i.test(document.querySelector('main').innerText), null, { timeout: 4000 }).then(() => p.evaluate(() => document.querySelector('main').innerText.match(/Respawn in \d+:\d\d/i)[0]), () => '');
        await shot('corner-respawn', 1440);
      }
      if (!next && st.fighter && st.fighter.lives > atReady.lives && st.fighter.lastPick && st.fighter.lastPick.life === st.fighter.life) next = st;
      if (next && down) break;   // a new life can also start at a segment rollover with no KO: wait for both
      await sleep(400);   // a KO-to-respawn window can be short in the DEV arena
    }
    ok(!!down, `the corner showed the respawn countdown while the fighter was down (${down ? '"' + down.page + '", respawn_at_ms ' + down.respawn_at_ms + ', KO\'d by ' + (down.last_life && down.last_life.ended_by) : 'never: the host reported ' + [...seenStates].join(', ')})`);
    const lp = next && next.fighter.lastPick;
    // 'queued': the ring was full, so the room locked this pick for this life and seats it when a place opens
    ok(lp && (lp.state === 'accepted' || lp.state === 'queued') && lp.life === (next && next.fighter.life) && lp.order.preset === 'brawler-zap' && JSON.stringify(lp.order.spread) === '[25,25,25,25]' && lp.order.zero === 20,
      `the corner's pick is the one filed for the next life after Ready (Ready came in life ${atReady.lives}, ${atReady.life}): life ${next && next.fighter.lives} locked in as ${lp && lp.order.preset}, spread ${lp && JSON.stringify(lp.order.spread)}, zero ${lp && lp.order.zero}% (${lp && lp.state}${lp && lp.reason ? ': ' + lp.reason : ''}; filed for ${lp && lp.life})`);
    if (next) {
      let w1 = null;
      for (let i = 0; i < 30 && !(w1 && w1.item_id === KITS['Brawler Zap'].weapon); i++) { const o = await p.evaluate(() => fetch('/room/observe').then((r) => r.json())); const me = o.fighters.find((f) => f.fighter_id === next.fighter.id); w1 = me && me.state === 'ring' ? (me.equipped || []).find((e) => e.slot === 'weapon') : null; if (!(w1 && w1.item_id === KITS['Brawler Zap'].weapon)) await sleep(2000); }
      ok(w1 && w1.item_id === KITS['Brawler Zap'].weapon, `the new life wears Brawler Zap's weapon (${w1 && w1.item_id}; presets.py: ${KITS['Brawler Zap'].weapon})`);
      // the page polls every second: wait for its poll to show the last life before reading both (up to 20 s)
      await p.waitForFunction(() => /You predicted/.test(document.querySelector('main').innerText) && /KO’d/.test(document.querySelector('main').innerText), null, { timeout: 20000 }).catch(() => {});
      const c1 = await corner(), t1 = await p.innerText('main'), pageC = await p.evaluate(() => ({ last: Snapin.corner.data && Snapin.corner.data.last_life, age: Math.round(performance.now() - Snapin.corner.at), timer: !!Snapin.corner.timer, mode: Snapin.view.mode, tab: Snapin.view.tab }));
      console.log('page corner state', JSON.stringify(pageC));
      // the first life is filed with no prediction (board 1's guide files none); a life after Ready carries its 25/25/25/25
      const filedFirst = c1.last_life && lifeNo(c1.last_life.life_id) <= lifeNo(atReady.life), pr = c1.last_life && c1.last_life.prediction;
      ok(c1.last_life && (filedFirst ? pr === null && /You predicted\s*nothing filed/.test(t1) : pr && pr.spread_bps.one === 2500 && /You predicted/.test(t1)) && /KO’d/.test(t1),
        `the corner shows the last life against the prediction filed for it (the Ready pick went to ${lp && lp.life}; ${c1.last_life && c1.last_life.life_id}: KOs ${c1.last_life && c1.last_life.ko_count}, ${filedFirst ? 'the first life, filed with none' : 'filed after Ready'}: ${pr ? 'predicted 1: ' + pr.spread_bps.one / 100 + '%' : 'no prediction'})`);
      await shot('corner-after-ko', 1440);
    }
    // × from the corner returns to the live arena, not a stub
    await p.goto(base + '/web/snapin/index.html?mode=workshop&tab=respawn&ws=' + encodeURIComponent(ws)); await ready();
    await Promise.all([p.waitForURL(/arena\.html/), click('close')]);
    ok(/\/web\/arena\.html/.test(p.url()), `× on the corner returns to the live arena (${p.url().replace(base, '')})`);
    // ---- five sheets, one per battle option, saved from the Persona tab
    const sheets = path.join(OUT, 'sheets'); fs.mkdirSync(sheets, { recursive: true });
    for (const name of Object.keys(KITS)) {
      await p.goto(base + '/web/snapin/index.html?mode=workshop&tab=battle'); await ready();
      await click('preset:' + name); await click('tab:persona');
      await p.fill('#name', 'Pip ' + name.split(' ')[1]);   // one name per option sheet: the file is named after it
      const [dl] = await Promise.all([p.waitForEvent('download'), click('sheet-download')]);
      await dl.saveAs(path.join(sheets, dl.suggestedFilename()));
    }
    let checked = '';
    try { checked = execFileSync('python3', ['-I', 'near/lore/check_personas.py', '--dir', sheets], { cwd: REPO }).toString(); } catch (e) { checked = String(e.stdout || '') + String(e.stderr || ''); }
    fs.writeFileSync(path.join(OUT, 'check_personas.txt'), checked);
    const presetsSeen = fs.readdirSync(sheets).map((f) => JSON.parse(fs.readFileSync(path.join(sheets, f))).game || {}).map((g) => g.preset || g.fight || '').join(', ');
    ok(/5\/5 valid/.test(checked), `five saved option sheets: check_personas.py --dir prints "${(checked.match(/\d+\/\d+ valid/) || ['?'])[0]}" (${presetsSeen})`);
    // ---- the arena gone: the corner says so
    await p.goto(base + '/web/snapin/index.html?mode=workshop&tab=respawn'); await ready();
    await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
    await p.waitForFunction(() => /Cannot reach the arena/.test(document.querySelector('main').innerText), null, { timeout: 20000 }).catch(() => {});
    ok(/Cannot reach the arena, so the corner has no fresh data/.test(await p.innerText('main')), 'with the arena stopped the corner says it has no fresh data and keeps retrying');
    await shot('corner-arena-gone', 1440);
    const own = errs.filter((e) => !/GL Driver Message/.test(e) && !/status of 502/.test(e) && !/^http 502 /.test(e));
    ok(own.length === 0, 'console clean (set aside: headless GL notes, the 502s after the arena was stopped)' + (own.length ? ': ' + own.slice(0, 4).join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 400)); try { await p.screenshot({ path: path.join(OUT, 'crash.png'), fullPage: true }); } catch (e2) { /* gone */ } }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  fs.writeFileSync(path.join(OUT, 'corner-case.json'), JSON.stringify({ pass, fail, at: new Date().toISOString(), frames, kits: KITS, report }, null, 1));
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed; frames in ${OUT}`);
  process.exit(fail ? 1 : 0);
})();
