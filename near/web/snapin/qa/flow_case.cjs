// F52 end to end: two first-time visitors snap a trenchie into the DEV arena from the live page, in a real browser.
// Visitor A at 1440, visitor B at 390 (separate browser contexts: separate storage, keys and tab locks).
// Each, through board 1's guide: arena CTA -> wallet (a wallet that cannot connect here, then the DEV throwaway account) ->
// battle options (every one clicked) -> claim or build -> personality (every temperament and quirk, the name) -> AI (NEAR AI
// Cloud: a refused key, then a good one) -> the check page (off until a cap is set, then Snap in) -> the join -> in the ring:
// the fighter is in /dev/players and drawn in arena.html, followed. Mid-flow reload, Back and Forward are checked.
// B first types A's name while A is in the ring: the name step catches it before any join. Both leave at the end.
// (Board 1's exact copy per state is board1_guide_case.cjs's; this case checks the flow end to end.)
// The model provider's key check is answered by this test (no player key exists here): labelled in the output, and
// a real key is Pat's click-through. The browser has no internet: every host but this machine's is cut (as a name that does
// not resolve) and any window a wallet opens is closed, so the wallet door fails the same way on every lane (with network,
// Meteor opened its real QR window and waited past the case's 45 s). Everything else is real: the DEV arena (snap_local.py), serve.py, the signed room
// protocol from the browser (room.js), WebCrypto keys, IndexedDB.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/flow_case.cjs [out-dir] [--arena http://127.0.0.1:PORT]
'use strict';
const { spawn } = require('child_process'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const NEAR = path.resolve(__dirname, '..', '..', '..');
const argv = process.argv.slice(2), arenaArg = argv.indexOf('--arena') >= 0 ? argv[argv.indexOf('--arena') + 1] : '';
const OUT = argv.find((a, i) => !a.startsWith('--') && argv[i - 1] !== '--arena') || path.join(os.tmpdir(), 'snapin-flow-e2e');
fs.mkdirSync(OUT, { recursive: true });
let pass = 0, fail = 0; const report = [];
const ok = (c, m) => { report.push((c ? 'PASS ' : 'FAIL ') + m); if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs'), G = require('./board1_flow.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || path.dirname(NEAR));

(async () => {
  let arena = null, arenaUrl = arenaArg;
  if (!arenaUrl) {
    const port = 20000 + Math.floor(Math.random() * 20000);
    arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
    arenaUrl = 'http://127.0.0.1:' + port;
  }
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const ws = 'ws://' + new URL(arenaUrl).host;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  let current = null, arenaStopped = false; const failed = [], overflow = [], consoleReads = [];
  // With no internet, NEAR Connect's own runtime manifest cannot load. These are the SDK's two default endpoints;
  // the focused wallet_manifest_case supplies a complete manifest and walks the real stock chooser instead.
  const WALLET_MANIFESTS = ['https://raw.githubusercontent.com/hot-dao/near-selector/refs/heads/main/repository/manifest.json', 'https://cdn.jsdelivr.net/gh/azbang/hot-connector/repository/manifest.json'];
  const isWalletCode = (u) => WALLET_MANIFESTS.includes(u.split('?')[0]);
  // one browser context (single-process Chromium does not survive a second); the two visitors use two origins,
  // 127.0.0.1 and localhost, so their storage, keys and tab locks are separate as two people's would be
  const ctx = await b.newContext();
  // no internet in this browser, on any lane: hosts other than this machine's (and the provider route below) do not resolve
  const LOCAL = new Set(['127.0.0.1', 'localhost']), cut = [];
  await ctx.route((u) => !LOCAL.has(u.hostname) && u.hostname !== 'cloud-api.near.ai', (route) => { cut.push(route.request().url()); return route.abort('namenotresolved'); });
  const popups = [];   // a window a wallet opens (Meteor's connect window) is closed at once and counted
  ctx.on('page', async (pg) => { if (await pg.opener()) { popups.push(pg.url()); await pg.close().catch(() => {}); } });
  await ctx.addInitScript(() => { const r = window.requestAnimationFrame.bind(window); window.requestAnimationFrame = (cb) => (window.__freeze ? 0 : r(cb)); });
  // the model provider's answer for the key check (labelled: no player key exists in this test)
  let keyAnswer = 401;
  await ctx.route('https://cloud-api.near.ai/**', (route) => keyAnswer === 200
      ? route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ id: 'test', object: 'chat.completion', model: 'deepseek-ai/DeepSeek-V4.1-Flash-1017', choices: [{ index: 0, message: { role: 'assistant', content: 'Ready when you are.' }, finish_reason: 'stop' }], usage: { prompt_tokens: 9, completion_tokens: 5 } }) })
      : route.fulfill({ status: 401, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ error: { message: 'Invalid API key', type: 'authentication_error' } }) }));
  const run = async (W, who, opts) => {
    const base = opts.origin;
    const p = await ctx.newPage(); const errs = []; current = p;
    await p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
    p.on('console', (m) => {
      if (m.type() !== 'error' && m.type() !== 'warning') return;
      const line = m.type() + ': ' + m.text().slice(0, 240) + ' @ ' + p.url().replace(base, '');
      // This fixture supplies prose, not plan JSON; only that exact provider parse diagnostic is expected.
      consoleReads.push((async () => {
        try {
          const args = m.args();
          if (m.type() === 'warning' && args.length === 2 && await args[0].jsonValue() === 'Trenchie AI order') {
            const event = await args[1].jsonValue();
            if (event && event.provider === 'nearai' && event.kind === 'parse' &&
                event.message === 'the answer had no complete JSON object') return;
          }
        } catch (e) { /* An unreadable diagnostic remains a console failure. */ }
        errs.push(line);
      })());
    });
    p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
    p.on('response', (r) => { if (r.status() >= 400 && !/cloud-api\.near\.ai/.test(r.url())) errs.push('http ' + r.status() + ' ' + r.url().replace(/^https?:\/\/[^/]+/, '')); });
    p.on('requestfailed', (r) => failed.push(r.url()));
    const tag = `${who}@${W}`, frames = [];
    const shot = async (name) => {
      const wide = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: innerWidth, over: [...document.querySelectorAll('#app *')].filter((e) => { const r = e.getBoundingClientRect(); return r.width && (r.right > innerWidth + 1 || r.left < -1); }).slice(0, 3).map((e) => e.tagName + '.' + (e.getAttribute('class') || '') + ':' + (e.textContent || '').trim().slice(0, 40)) }));
      overflow.push([name, W, wide.sw <= wide.w && wide.over.length === 0, wide]);
      const f = `${String(frames.length + 1).padStart(2, '0')}-${name}-${W}.png`; await p.evaluate(() => { window.__freeze = true; }); await sleep(200); await p.screenshot({ path: path.join(OUT, f), fullPage: !/arena/.test(name), timeout: 30000 }); await p.evaluate(() => { window.__freeze = false; }); frames.push(f); };
    const ready = () => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
    const step = () => p.evaluate(() => window.Snapin && Snapin.view.step);
    // keyboard: Tab until the control with this data-act has focus; every stop on the way must show a ring
    const tabTo = async (act) => {
      const stops = [];
      for (let i = 0; i < 60; i++) {
        await p.keyboard.press('Tab');
        const f = await p.evaluate(() => { const e = document.activeElement; if (!e || e === document.body) return null; const st = getComputedStyle(e); return { act: e.dataset.act || e.id || e.tagName, ring: (st.outlineStyle !== 'none' && parseFloat(st.outlineWidth) >= 2) || /rgb/.test(st.boxShadow) }; });
        if (!f) continue; stops.push(f);
        if (f.act === act) return { found: true, stops, bare: stops.filter((x) => !x.ring).map((x) => x.act) };
      }
      return { found: false, stops, bare: stops.filter((x) => !x.ring).map((x) => x.act) };
    };
    const click = async (act) => { await p.click(`[data-act="${act}"]`); await sleep(120); };
    const live = async () => { await p.waitForFunction(() => document.getElementById('status').className === 'live' && document.querySelector('#world [data-panel="feed"]'), null, { timeout: 150000 }); await sleep(1500); };
    const sweep = async (selector, label) => {   // click every option in a group; each must stay on the step and press
      const acts = await p.$$eval(selector, (els) => els.map((e) => e.dataset.act));
      let pressed = 0;
      for (const a of acts) { await click(a); if (await p.$eval(`[data-act="${a}"]`, (e) => e.getAttribute('aria-pressed') === 'true').catch(() => false)) pressed++; }
      ok(acts.length > 0 && pressed === acts.length, `${tag}: ${label}: ${pressed}/${acts.length} options clicked and shown as chosen`);
      return acts;
    };
    const t = {};
    // ---- the live page and its call to action
    await p.goto(base + '/web/arena.html?ws=' + encodeURIComponent(ws), { waitUntil: 'load' }); await live();
    await shot('arena-cta');
    await Promise.all([p.waitForURL(/snapin\/index\.html/), p.click('#snapin-cta')]); await ready();
    ok((await step()) === 'wallet' && /Connect a NEAR wallet/.test(await p.innerText('#app')) && /Its fights and gear are on testnet\./.test(await p.innerText('#app')) && !/Mainnet/.test(await p.innerText('#app')), `${tag}: the call to action opens board 1's wallet step, which says testnet (no "Mainnet")`);
    await shot('wallet');
    // ---- wallet: one that cannot connect here (no wallet app or network in this browser), then the DEV throwaway account
    const cutBefore = cut.length, w0 = Date.now();
    await click('g:wallet:choose');
    await p.waitForFunction(() => /Wallet list didn’t load/.test((document.querySelector('#feedback') || {}).textContent || ''), null, { timeout: 45000 }).catch(() => {});
    const wmsg = await p.$eval('#feedback', (e) => e.textContent).catch(() => '');
    ok(wmsg === 'Wallet list didn’t load; try again.' && (await step()) === 'wallet', `${tag}: a wallet that cannot connect says so plainly and leaves every door open, in ${((Date.now() - w0) / 1000).toFixed(1)} s with ${cut.length - cutBefore} outside requests cut and ${popups.length} wallet windows closed so far: "${wmsg.slice(0, 140)}"`);
    await shot('wallet-error');
    if (opts.keyboard) {
      const k = await tabTo('g:wallet:dev-throwaway');
      ok(k.found && k.bare.length === 0, `${tag}: keyboard: Tab reaches "Throwaway account" in ${k.stops.length} stops, every stop with a focus ring` + (k.bare.length ? ' (no ring: ' + k.bare.join(', ') + ')' : ''));
      await p.keyboard.press('Enter'); await sleep(400);
    } else { await click('g:wallet:dev-throwaway'); await sleep(300); }
    t.wallet = Date.now();
    ok((await step()) === 'presets', `${tag}: the DEV throwaway account connects and moves on`);
    await p.goBack(); await sleep(400);
    const acct = await p.evaluate(() => Snapin.state.wallet);
    ok((await step()) === 'wallet' && acct && /^[0-9a-f]{64}$/.test(acct.accountId) && acct.network === 'testnet' && /Connected: [0-9a-f]{12}…[0-9a-f]{8}/.test(await p.innerText('#app')), `${tag}: Back shows the connected account (${acct && acct.accountId.slice(0, 12)}…, testnet)`);
    await shot('wallet-connected');
    await click('g:step:presets');
    // ---- battle options
    await shot('presets');
    await sweep('.presets [data-act^="g:preset:"]', 'battle options');
    await click('g:preset:' + opts.preset);
    if (opts.build) { await click('g:build'); ok((await step()) === 'personality', `${tag}: "Build a fighter" goes on to the name and personality, with no claim`); }
    else {
      await click('g:use'); await p.waitForFunction(() => Snapin.view.step === 'personality', null, { timeout: 20000 }).catch(() => {});
      ok(await p.evaluate(() => Snapin.state.claim && Snapin.state.claim.dev === true), `${tag}: "Use this preset" records the DEV claim of its premint persona`);
    }
    ok((await step()) === 'personality', `${tag}: on to personality`);
    // ---- personality, then Back and reload
    await sweep('[data-act^="g:temper:"]', 'temperaments'); await click('g:temper:' + opts.temper);
    const quirks = await p.$$eval('[data-act^="g:quirk:"]', (els) => els.map((e) => e.dataset.act));
    const had = await p.evaluate(() => Snapin.state.quirks.slice().sort());   // a claimed persona arrives with its own quirks
    for (const q of quirks) { await click(q); await click(q); }   // each flipped twice: back where it was
    const back = await p.evaluate(() => Snapin.state.quirks.slice().sort());
    for (const q of had) await click('g:quirk:' + q);   // clear the claimed ones, then keep two (board 1: up to 2)
    for (const q of quirks.slice(0, 2)) await click(q);
    ok(JSON.stringify(back) === JSON.stringify(had) && (await p.evaluate(() => Snapin.state.quirks.length)) === 2,
      `${tag}: all ${quirks.length} quirks toggle on and off (back to ${had.length ? 'the claimed ' + had.join(', ') : 'none'}); two kept`);
    await p.fill('#name', opts.firstName || opts.name); await sleep(900);
    if (opts.firstName) {
      // a name already in the ring is caught on this step now, before any join: a plain line, and Next stays off
      await p.waitForFunction((n) => document.body.innerText.includes('✗ ' + n + ' is in the ring now. Pick another name.'), opts.firstName, { timeout: 15000 }).catch(() => {});
      const clash = await p.evaluate(() => ({ text: document.querySelector('#app').innerText, off: !!document.querySelector('.bar .gold[disabled]') }));
      ok(clash.text.includes('✗ ' + opts.firstName + ' is in the ring now. Pick another name.') && clash.off && /Needs a name/.test(clash.text), `${tag}: a name already in the ring is caught on the name step, before any join, and Next: AI stays off`);
      await shot('name-in-ring');
      await p.fill('#name', opts.name); await p.waitForFunction(() => /✓ Free/.test(document.body.innerText), null, { timeout: 15000 }).catch(() => {});
    }
    await shot('personality');
    await p.goBack(); await sleep(400);
    ok((await step()) === 'presets', `${tag}: Back from personality returns to the fighter step (${await step()})`);
    await p.goForward(); await sleep(400);
    await p.reload(); await ready(); await sleep(600);
    ok((await step()) === 'personality' && (await p.inputValue('#name')) === opts.name, `${tag}: Forward and reload land on personality with the name kept`);
    await click('g:step:doors');
    // ---- AI
    ok((await step()) === 'doors', `${tag}: on to the AI step`);
    await shot('ai');
    await click('g:door:key:NEAR AI Cloud'); await sleep(300); await shot('ai-key');
    await p.fill('#key', 'sk-not-a-real-key'); keyAnswer = 401; await click('g:test');
    await p.waitForFunction(() => /The provider refused this key/.test(document.body.innerText), null, { timeout: 20000 }).catch(() => {});
    ok(/✗ The provider refused this key\. Copy it again, all of it\./.test(await p.innerText('#app')) && !!(await p.$('.bar .gold[disabled]')), `${tag}: a refused key says so and Next: check stays off (provider answer: test-supplied 401)`);
    await shot('ai-bad-key');
    await p.fill('#key', 'sk-test-player-key'); keyAnswer = 200; await click('g:test');
    await p.waitForFunction(() => /It answered/.test(document.body.innerText), null, { timeout: 20000 }).catch(() => {});
    ok(await p.evaluate(() => /✓ It answered/.test(document.body.innerText) && !!Snapin.state.door && Snapin.state.door.door === 'NEAR AI Cloud'), `${tag}: a working key answers and is the AI (provider answer: test-supplied 200)`);
    await shot('ai-connected');
    // ---- the check page: off until the cap is set, then Snap in (it replaces the terms and their ticks)
    await click('g:step:agree');
    await p.waitForFunction(() => window.Snapin && Snapin.view.terms && Snapin.view.terms.version, null, { timeout: 20000 });
    ok((await step()) === 'agree' && /Needs an hourly cap/.test(await p.innerText('#app')) && !!(await p.$('.bar .gold[disabled]')), `${tag}: the check page keeps Snap in off and names what is missing: "Needs an hourly cap"`);
    await click('g:ai'); await click('g:cap:0.20'); await click('g:step:agree');
    await p.waitForFunction(() => !!document.querySelector('[data-act="g:snap"]'), null, { timeout: 20000 });
    ok(/NEAR AI Cloud · answered/.test(await p.innerText('#app')) && /\$0\.20/.test(await p.innerText('#app')), `${tag}: the check page says what is true: "NEAR AI Cloud · answered", cap $0.20`);
    await shot('check');
    const guideUrl = p.url();
    if (opts.keyboard) {
      const k = await tabTo('g:snap');
      ok(k.found && k.bare.length === 0, `${tag}: keyboard: Tab reaches "Snap in" with a focus ring on every stop` + (k.bare.length ? ' (no ring: ' + k.bare.join(', ') + ')' : ''));
      await p.keyboard.press('Enter');
    } else await click('g:snap');
    // ---- the join: board 1 lands on the trenchie's own panel in the arena (SPEC 'fight')
    const where = await G.afterSnap(p, { guideUrl, backToGuide: false, timeout: 90000 }).catch((e) => 'failed: ' + e.message);
    await p.waitForFunction(() => { const e = document.getElementById('b1-panel'); return e && !e.hidden && e.innerText.length > 0; }, null, { timeout: 30000 }).catch(() => {});
    const pan = await p.evaluate(() => { const e = document.getElementById('b1-panel'); return e && !e.hidden ? e.innerText.replace(/\s+/g, ' ') : ''; }).catch(() => '');
    ok(where === 'arena' && pan.includes(opts.name), `${tag}: Snap in lands on the arena with the trenchie's own panel (${where}: "${pan.slice(0, 70)}")`);
    await shot('arena-panel');
    const took = await p.evaluate(() => { try { return JSON.parse(localStorage.getItem('trenchie.snapin.v1')).timing; } catch (e) { return null; } }); t.timing = took;
    await p.goto(guideUrl.replace(/([?&])step=[^&]*/, '$1step=ring')); await ready();
    await p.waitForFunction(() => { const s = window.SnapRoom && SnapRoom.status(); return s && (s.phase === 'in' || s.phase === 'error'); }, null, { timeout: 90000 });
    let st = await p.evaluate(() => SnapRoom.status());
    t.ring = Date.now();
    ok(st.phase === 'in' && st.fighter && st.fighter.id === 'dev-' + opts.name.toLowerCase(), `${tag}: in the ring as ${st.fighter && st.fighter.id} (${st.message || 'no message'})`);
    t.shown = took && took.ring && took.wallet ? Math.round((took.ring - took.wallet) / 1000) : null;
    if (opts.timed) ok(t.shown !== null && t.shown < 180, `${tag}: wallet to ring ${t.shown} s by the page's own clock on the direct path (target < 180 s; clicks at machine speed)`);
    else console.log(`NOTE ${tag}: wallet to ring ${t.shown} s on the sweep path (every option clicked, a name clash on the way): not a timing measure`);
    await sleep(800); await shot('ring');
    // with no prediction filed (board 1 files none), the room locks "none" when the life's 2 s prediction window closes, and
    // only then does the first life start: read until it has (10 s at most)
    let me = null;
    for (let i = 0; i < 20; i++) {
      const players = await p.evaluate(async () => (await fetch('/dev/players')).json());
      me = players.find((x) => x.fighter_id === 'dev-' + opts.name.toLowerCase());
      if (me && (me.state !== 'bench' || Number(String(me.life_id || '').split(':life:')[1]) > 0)) break;
      await sleep(500);
    }
    // a KO on the way leaves it on the bench for the 45 s respawn wait (a later life_id, :life:1 and up); the first life is never on the bench here
    const laterLife = me && Number(String(me.life_id || '').split(':life:')[1]) > 0;
    ok(me && (me.state !== 'bench' || laterLife) && me.preset === opts.presetId, `${tag}: /dev/players lists ${me && me.fighter_id} (${me && me.state}, ${me && me.life_id}, preset ${me && me.preset})`);
    // ---- reload in the ring: the same fighter carries on
    await p.reload(); await ready();
    await p.waitForFunction(() => SnapRoom.status().phase === 'in', null, { timeout: 30000 }).catch(() => {});
    const st2 = await p.evaluate(() => SnapRoom.status());
    ok(st2.phase === 'in' && st2.fighter.id === st.fighter.id && /In the arena/.test(await p.innerText('main')), `${tag}: a reload in the ring carries on with the same fighter (${st2.phase})`);
    // ---- an earlier step while the fighter is in: a banner and a way back; Snap in again does not start a second join
    await p.goto(opts.origin + '/web/snapin/index.html?step=doors'); await ready();
    await p.waitForFunction(() => /is in the arena now/.test(document.querySelector('#app').innerText), null, { timeout: 30000 }).catch(() => {});
    ok(/DEV .* is in the arena now/i.test(await p.innerText('#app')), `${tag}: a reload on an earlier step says the fighter is in the arena, with a way back`);
    await p.goto(opts.origin + '/web/snapin/index.html?step=agree'); await ready();
    await p.waitForFunction(() => window.Snapin && Snapin.view.terms && Snapin.view.terms.version && SnapRoom.status().phase === 'in', null, { timeout: 30000 }).catch(() => {});
    await click('g:snap'); await sleep(1500);
    const twice = await p.evaluate(async () => ({ step: Snapin.view.step, phase: SnapRoom.status().phase, players: (await (await fetch('/dev/players')).json()).length }));
    ok(twice.step === 'ring' && twice.phase === 'in' && !/another tab/.test(await p.innerText('main')), `${tag}: Snap in while already in goes to the ring view, no second join, no "another tab" (${JSON.stringify(twice)})`);
    await click('back-ring').catch(() => {});
    // ---- watch it in the arena
    await Promise.all([p.waitForURL(/arena\.html/), click('watch-mine')]); await live();
    await p.waitForFunction((id) => document.querySelector('.inset') && !document.querySelector('.inset').hidden, st.fighter.id, { timeout: 20000 }).catch(() => {});
    // the HUD draws a fighter's tag once its body is on screen; under load that can trail the follow view by seconds
    await p.waitForFunction((nm) => [...document.querySelectorAll('.atag')].some((e) => e.textContent.toLowerCase().includes(nm.toLowerCase())), opts.name, { timeout: 45000 }).catch(() => {});
    const view = await p.evaluate((nm) => ({ tags: [...document.querySelectorAll('.atag')].map((e) => e.textContent), inset: !!document.querySelector('.inset:not([hidden])'), cta: document.getElementById('snapin-cta').innerText.replace(/\s+/g, ' '), url: location.search }), opts.name);
    ok(view.tags.some((x) => x.toLowerCase().includes(opts.name.toLowerCase())), `${tag}: arena.html draws the fighter's tag (${view.tags.filter((x) => x.toLowerCase().includes(opts.name.toLowerCase())).join(', ') || 'none of: ' + view.tags.join(', ')})`);
    ok(view.inset && /follow=/.test(view.url), `${tag}: "Watch your trenchie" opens the follow view on it`);
    await p.waitForFunction(() => { const e = document.getElementById('b1-panel'); return e && !e.hidden && e.innerText.length > 0; }, null, { timeout: 20000 }).catch(() => {});
    const own = await p.evaluate(() => { const e = document.getElementById('b1-panel'); return e && !e.hidden ? e.innerText.replace(/\s+/g, ' ') : ''; }).catch(() => '');
    ok(own.includes(opts.name) && !(await p.isVisible('#snapin-cta')), `${tag}: the arena shows the trenchie's own panel in place of the call to action: "${own.slice(0, 70)}"`);
    await shot('arena-mine');
    t.errs = errs; t.p = p; t.tag = tag; t.frames = frames; t.st = st; t.origin = opts.origin;
    return t;
  };
  let A = null, B = null;
  try {
    A = await run(1440, 'A', { origin: 'http://127.0.0.1:' + web.m, timed: true, keyboard: true, name: 'Pipshoal', preset: 'Hunter Lunge', presetId: 'hunter-lunge', temper: 'gruff', build: false });
    B = await run(390, 'B', { origin: 'http://localhost:' + web.m, firstName: 'Pipshoal', name: 'Kelpie', preset: 'Looter Lob', presetId: 'looter-lob', temper: 'serene', build: true });
    // ---- leaving: from the corner of each
    for (const T of [B, A]) {
      const p = T.p;
      const before = await p.evaluate(() => { const s = SnapRoom.status(); return { phase: s.phase, message: s.message, error: s.error }; });
      ok(before.phase === 'in', `${T.tag}: still in the ring while the other visitor played (${JSON.stringify(before).slice(0, 300)})`);
      // the guide's ring view, where Leave is (the panel in the arena stands in for the call to action)
      await p.goto(T.origin + '/web/snapin/index.html?step=ring&ws=' + encodeURIComponent(ws)); await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
      await p.waitForFunction(() => SnapRoom.status().phase === 'in', null, { timeout: 30000 }).catch(() => {});
      await p.click('[data-act="leave"]');
      await p.waitForFunction(() => SnapRoom.status().phase === 'ended', null, { timeout: 30000 }).catch(() => {}); await sleep(1500);
      const s = await p.evaluate(() => SnapRoom.status());
      let gone = false;
      for (let i = 0; i < 20 && !gone; i++) { gone = await p.evaluate(async (id) => !(await (await fetch('/dev/players')).json()).some((x) => x.fighter_id === id && x.state === 'alive'), T.st.fighter.id); if (!gone) await sleep(1000); }
      ok(s.phase === 'ended' && /Snap in again/.test(await p.innerText('main')), `${T.tag}: "Leave the arena" ends the session and offers "Snap in again" (${s.phase}: ${s.message})`);
      await p.screenshot({ path: path.join(OUT, `99-left-${T.tag.split('@')[1]}.png`), fullPage: true });
      ok(gone, `${T.tag}: after leaving the fighter is no longer alive in /dev/players`);
      await p.reload(); await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 }); await sleep(800);
      ok(/swam home/i.test(await p.innerText('main')), `${T.tag}: after a reload the page still says the trenchie swam home`);
    }
    // snap in again at once: leaving read the round's result, so the DEV host does not hold the next join
    {
      const p = A.p; const t0 = Date.now();
      await p.click('[data-act="join"]');
      await p.waitForFunction(() => { const s = SnapRoom.status(); return s.phase === 'in' || s.phase === 'error'; }, null, { timeout: 90000 }).catch(() => {});
      const s = await p.evaluate(() => SnapRoom.status());
      ok(s.phase === 'in', `A@1440: "Snap in again" right after leaving puts the fighter back in ${Math.round((Date.now() - t0) / 1000)} s (${s.message || 'no hold'})`);
      const tm = await p.evaluate(() => Snapin.state.timing);
      ok(tm && tm.ring && tm.ring - tm.wallet === A.timing.ring - A.timing.wallet && /Wallet to the ring/.test(await p.innerText('main')), `A@1440: "Wallet to the ring" is measured once and does not grow on a rejoin (${Math.round((tm.ring - tm.wallet) / 1000)} s)`);
      if (arena) {
        // the arena stopped while the fighter is in the ring: a reconnecting state, no stale life, no shell command
        await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
        await p.waitForFunction(() => SnapRoom.status().phase === 'offline', null, { timeout: 30000 }).catch(() => {});
        const main = await p.innerText('main');
        ok(/Reconnecting/i.test(main) && /Try again/.test(main) && /Keep watching/.test(main) && !/LIFE \d/i.test(main) && !/python3|snap_local/.test(main), `A@1440: arena stopped while in the ring: "${main.replace(/\s+/g, ' ').slice(0, 160)}"`);
        await p.screenshot({ path: path.join(OUT, '97-arena-stopped-in-ring-1440.png'), fullPage: true });
        arenaStopped = true;
      } else { await p.click('[data-act="leave"]'); await p.waitForFunction(() => SnapRoom.status().phase === 'ended', null, { timeout: 15000 }).catch(() => {}); }
    }
    // the arena gone: once the seat is lost, a plain message and a way back on the next try
    if (arena) {
      const p = A.p;
      await p.waitForFunction(() => SnapRoom.status().phase === 'ended', null, { timeout: 60000 }).catch(() => {});
      await p.click('[data-act="join"]');
      await p.waitForFunction(() => SnapRoom.status().phase === 'error', null, { timeout: 30000 }).catch(() => {});
      const s = await p.evaluate(() => SnapRoom.status()), main = await p.innerText('main');
      ok(s.phase === 'error' && /Cannot reach the arena/.test(s.message) && /Try again/.test(main) && /Keep watching/.test(main), `A@1440: with the arena stopped: "${s.message}", with Try again and Keep watching`);
      await p.screenshot({ path: path.join(OUT, '98-arena-gone-1440.png'), fullPage: true });
    }
    const wideBad = overflow.filter((x) => !x[2]);
    ok(overflow.length > 20 && wideBad.length === 0, `no sideways scroll and nothing past the screen edge on ${overflow.length} captured screens` + (wideBad.length ? ': ' + JSON.stringify(wideBad.slice(0, 3)) : ''));
    await Promise.all(consoleReads);
    const all = [...A.errs, ...B.errs];
    const offline = failed.filter(isWalletCode), other = failed.filter((u) => !isWalletCode(u));
    let unresolved = all.filter((e) => /net::ERR_NAME_NOT_RESOLVED/.test(e)).length;
    ok(other.length === 0 && unresolved === offline.length && cut.every(isWalletCode), `failed requests: ${offline.length} stock manifest requests with no internet in this browser (${cut.length} cut; ${popups.length} wallet windows closed${popups.length ? ': ' + [...new Set(popups)].join(', ') : ''}) (${[...new Set(offline.map((u) => u.split('?')[0]))].join(', ')}), ${other.length} others` + (other.length ? ': ' + other.join(', ') : ''));
    const own = all.filter((e) => !(/net::ERR_NAME_NOT_RESOLVED/.test(e) && other.length === 0)).filter((e) => !(/^http 400 \/dev\/identity$/.test(e) || /status of 400/.test(e))).filter((e) => !(arena && (/status of 502/.test(e) && /index\.html\?step=ring/.test(e) || /^http 502 \/(room|dev)\//.test(e)))).filter((e) => !/GL Driver Message \(OpenGL, Performance, GL_CLOSE_PATH_NV, High\): GPU stall due to ReadPixels/.test(e) && !/cloud-api\.near\.ai.*401|status of 401/.test(e));
    fs.writeFileSync(path.join(OUT, 'console.json'), JSON.stringify(all, null, 1));
    ok(own.length === 0, 'console clean in both visitors (set aside: the supplied prose answer’s parse diagnostic, headless GL driver notes, the test-supplied 401, the wallet-manifest fetches counted above, the 502s of the stopped-arena check)' + (own.length ? ': ' + own.slice(0, 5).join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 400)); try { if (current) await current.screenshot({ path: path.join(OUT, 'crash.png'), fullPage: true }); console.log('crash at', current && current.url()); } catch (e2) { /* gone */ } }
  await b.close().catch(() => {});
  if (arena) { await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {}); arena.child.kill(); }
  web.child.kill();
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  const summary = { pass, fail, at: new Date().toISOString(), wallet_to_ring_s: { A: A && A.shown, B: B && B.shown }, frames: { A: A && A.frames, B: B && B.frames }, provider_answers: 'test-supplied (401 then 200) for cloud-api.near.ai; everything else real', report };
  fs.writeFileSync(path.join(OUT, 'flow-case.json'), JSON.stringify(summary, null, 1));
  console.log(`${pass} passed, ${fail} failed; frames in ${OUT}`);
  process.exit(fail ? 1 : 0);
})();
