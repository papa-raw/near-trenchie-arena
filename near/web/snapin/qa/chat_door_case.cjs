// The order box with no AI door and with an agent door, in a real browser on the DEV arena: no order form at all (no text
// box, counter or Send), only the heading and where orders go, "Pick an AI door" a link to the guide's AI step; nothing is
// sent; and on load the box never shows another state first (no flash). A passing state (no key) keeps its disabled form.
// A visitor snaps in through the guide (NEAR AI Cloud, the provider's key check answered by this case, as in corner_case),
// then the saved door is switched and the page reloaded, in the ring each time:
//  * no door           -> "Pick an AI door to give orders." (the fighter card beside it says why), the link opens the AI step
//  * an agent door      -> "Orders go to your agent: type them in its session." (Claude through Claude Code: the agent
//                          drives through SNAP.md, the page has no provider for it; the card says so)
//  * NEAR AI Cloud, cap, no key (a passing state) -> the disabled form, no example order in it
//  * NEAR AI Cloud, key and cap (the control) -> box on
// From navigation on, every DOM change and every frame records the box (on/off and its reason line); from the frame the box
// first appears, the next second must hold one state only. A submit from the off box must not reach SnapBrain.tell.
// The arena page (arena.html, the compact box beside the follow view) is checked once with no door.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/chat_door_case.cjs [out-dir]
'use strict';
const { spawn } = require('child_process'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const OUT = process.argv[2] || path.join(os.tmpdir(), 'snapin-chat-door'); fs.mkdirSync(OUT, { recursive: true });
const SAVE = 'trenchie.snapin.v1', CAP = 'trenchie.snapin.cap';
const NO_DOOR = 'Pick an AI door to give orders.', AGENT = 'Orders go to your agent: type them in its session.', NO_DOOR_ARENA = 'No AI door picked: Pick an AI door to give orders.';
const KEY = 'trenchie.snapin.key.NEAR AI Cloud';
const AGENT_ARENA = 'Your agent drives this trenchie (it joined through SNAP.md); type orders in its session.';
// the link's box (a 44 px target like every text link) and whether it is on screen
const linkBox = (pg, sel) => pg.evaluate((q) => { const a = document.querySelector(q); if (!a) return null; a.scrollIntoView({ block: 'center' }); const r = a.getBoundingClientRect();
  return { h: Math.round(r.height * 10) / 10, w: Math.round(r.width), onScreen: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth }; }, sel);
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
  const base = 'http://127.0.0.1:' + web.m, ws = 'ws://127.0.0.1:' + port;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const ctx = await b.newContext();
  // the provider's answers (no player key exists here): the key check at once; in the control the brain's calls are answered
  // after 5 s, so the measured second is the box's own state on load, not a reply the case made up
  let slow = false;
  await ctx.route('https://cloud-api.near.ai/**', async (r) => { if (slow) await sleep(5000); return r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ id: 't', object: 'chat.completion', choices: [{ index: 0, message: { role: 'assistant', content: '{}' }, finish_reason: 'stop' }], usage: { prompt_tokens: 9, completion_tokens: 2 } }) }).catch(() => {}); });
  // the box, recorded on every DOM change and every frame from navigation on (state changes only)
  await ctx.addInitScript(() => {
    const t0 = performance.now(), log = (window.__boxLog = []);
    const rec = () => {
      const blk = document.querySelector('[data-chat]'), box = document.querySelector('[data-chat] #order'), why = document.querySelector('[data-chat] #order-state'), send = document.querySelector('[data-chat] .chat-send');
      const text = why ? why.textContent.trim().slice(0, 140) : '';
      const s = box ? (box.disabled ? 'off' : 'on') + (send && !send.disabled ? '+send' : '') + ' | ' + text : blk && blk.dataset.door ? 'door:' + blk.dataset.door + ' | ' + text : blk ? 'other' : 'none';
      if (!log.length || log[log.length - 1][1] !== s) log.push([Math.round(performance.now() - t0), s]);
    };
    new MutationObserver(rec).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    const f = () => { rec(); if (performance.now() - t0 < 8000) requestAnimationFrame(f); }; requestAnimationFrame(f);
  });
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  const ready = () => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
  const click = async (act) => { await p.click(`[data-act="${act}"]`); await sleep(150); };
  // from the first frame with a box, one second: every state seen
  const firstSecond = async (sel) => {
    await p.waitForFunction((s) => !!document.querySelector(s), sel, { timeout: 90000 });
    const at = await p.evaluate(() => { const l = window.__boxLog; const i = l.findIndex((x) => x[1] !== 'none'); return i < 0 ? null : l[i][0]; });
    await p.waitForFunction((a) => performance.now() - performance.timeOrigin >= 0 && window.__boxLog && (performance.now() >= a + 1000), at, { timeout: 30000 }).catch(() => {});
    await sleep(200);
    const log = await p.evaluate(() => window.__boxLog);
    const seen = log.filter((x) => x[0] >= at && x[0] <= at + 1000 && x[1] !== 'none');
    return { at, states: [...new Set(seen.map((x) => x[1]))], log };
  };
  let keyKept = null;
  const setDoor = async (door, cap, noKey) => p.evaluate(([k, d, ck, c, kk, nk, keep]) => {
    const v = JSON.parse(localStorage.getItem(k) || '{}'); v.door = d; localStorage.setItem(k, JSON.stringify(v));
    if (c == null) localStorage.removeItem(ck); else localStorage.setItem(ck, String(c));
    const was = localStorage.getItem(kk); if (nk) localStorage.removeItem(kk); else if (keep && !was) localStorage.setItem(kk, keep); return was;
  }, [SAVE, door, CAP, cap, KEY, !!noKey, keyKept]).then((was) => { if (was) keyKept = was; });
  // a door state: the block has no text box, counter or Send, and a send from the page reaches nothing
  const noForm = () => p.evaluate(() => { const b = document.querySelector('[data-chat]'); return { door: b && b.dataset.door, input: !!b.querySelector('textarea, input'), counter: !!b.querySelector('#order-count'), send: !!b.querySelector('button, .chat-send'), heading: (b.querySelector('.eyebrow') || {}).textContent || '', line: (b.querySelector('#order-state') || {}).textContent || '', links: [...b.querySelectorAll('a')].map((a) => [a.textContent, a.getAttribute('href')]) }; });
  const sendReaches = () => p.evaluate(async () => {
    let n = 0; const real = window.SnapBrain.tell; window.SnapBrain.tell = async (t) => { n++; return real(t); };
    window.SnapChat.state.draft = 'grab the loot'; await window.SnapChat.send(() => {}); await new Promise((res) => setTimeout(res, 400));
    window.SnapBrain.tell = real; window.SnapChat.state.draft = ''; return n;
  });
  try {
    await p.setViewportSize({ width: 1440, height: 900 });
    // ---- snap in through the guide (NEAR AI Cloud), as corner_case does
    await p.goto(base + '/web/snapin/index.html?step=wallet&ws=' + encodeURIComponent(ws)); await ready();
    await click('wallet-dev'); await click('preset:Hunter Lunge'); await click('claim');
    await p.fill('#name', 'Doorpip'); await click('step:doors');
    await click('ai:door:NEAR AI Cloud'); await p.fill('#key', 'sk-test-player-key'); await click('ai:test');
    await p.waitForFunction(() => SnapDoors.state.state === 'connected', null, { timeout: 20000 }); await click('ai:continue');
    await p.waitForFunction(() => Snapin.view.terms && Snapin.view.terms.version, null, { timeout: 20000 });
    for (const id of ['#agree-ai', '#agree-public', '#agree-gear']) await p.check(id);
    await click('agree');
    await p.waitForFunction(() => SnapRoom.status().phase === 'in', null, { timeout: 90000 });
    const saved = await p.evaluate((k) => JSON.parse(localStorage.getItem(k)).door, SAVE);
    ok(saved && saved.door === 'NEAR AI Cloud', `snapped in with the NEAR AI Cloud door (${saved && saved.door})`);
    const ringUrl = p.url();
    // ---- each door, a reload in the ring
    const runs = [['no door', null, null, false, 'door:no-door | ' + NO_DOOR], ['agent door', { door: 'Claude', route: 'plan', identity: 'Claude Code', keyMask: '' }, null, false, 'door:agent-door | ' + AGENT],
      ['NEAR AI Cloud, cap, no key (passing state)', saved, 0.5, true, 'off'], ['NEAR AI Cloud, key and cap (control)', saved, 0.5, false, 'on']];
    for (const [label, door, cap, noKey, want] of runs) {
      await setDoor(door, cap, noKey); slow = want === 'on';
      await p.goto(ringUrl); await ready();
      const r = await firstSecond('[data-chat]');
      fs.writeFileSync(path.join(OUT, 'box-' + label.replace(/\W+/g, '-') + '.json'), JSON.stringify(r.log, null, 1));
      await p.screenshot({ path: path.join(OUT, 'ring-' + label.replace(/\W+/g, '-') + '.png'), fullPage: true });
      if (want.startsWith('door:')) {
        ok(r.states.length === 1 && r.states[0] === want, `${label}: from the block's first frame (${r.at} ms after navigation) its first second shows one state, "${want}" (seen: ${JSON.stringify(r.states)})`);
        const n = await noForm();
        ok(!n.input && !n.counter && !n.send && /^Orders for /.test(n.heading), `${label}: no text box, counter or Send, only the heading "${n.heading}" and the line "${n.line}"`);
        ok((await sendReaches()) === 0, `${label}: a send from the page (SnapChat.send with a draft) does not reach the AI`);
        if (label === 'no door') {
          ok(n.links.length === 1 && n.links[0][0] === 'Pick an AI door', `${label}: "Pick an AI door" is a link (${JSON.stringify(n.links)})`);
          for (const W of [1440, 390]) {
            if (W === 390) { await p.setViewportSize({ width: 390, height: 844 }); await p.goto(ringUrl); await ready(); await p.waitForSelector('[data-chat] a', { timeout: 30000 }); }
            const lb = await linkBox(p, '[data-chat] a');
            ok(lb && lb.h >= 44 && lb.onScreen, `${label} at ${W}: the link is on screen and its box is ${lb && lb.h} px tall (≥ 44)`);
            if (W === 390) { await p.screenshot({ path: path.join(OUT, 'ring-no-door-390.png'), fullPage: true }); await p.setViewportSize({ width: 1440, height: 900 }); await p.goto(ringUrl); await ready(); await p.waitForSelector('[data-chat] a', { timeout: 30000 }); }
          }
          await Promise.all([p.waitForURL(/step=doors/), p.click('[data-chat] a')]); await ready();
          const v = await p.evaluate(() => ({ step: Snapin.view.step, mode: Snapin.view.mode, text: document.querySelector('main').innerText }));
          ok(v.mode === 'flow' && v.step === 'doors' && /NEAR AI Cloud/.test(v.text), `${label}: the link opens the guide's AI step (${p.url().replace(base, '')}: mode ${v.mode}, step ${v.step})`);
        }
      } else if (want === 'off') {
        ok(r.states.length === 1 && /^off \| No key in this browser/.test(r.states[0]), `${label}: a passing state keeps the disabled form, off from its first frame (seen: ${JSON.stringify(r.states)})`);
        const ph = await p.getAttribute('[data-chat] #order', 'placeholder');
        ok(ph === '', `${label}: the off box shows no example order to type (placeholder ${JSON.stringify(ph)})`);
      } else {
        ok(r.states.length >= 1 && r.states.every((x) => /^on/.test(x)), `${label}: the box is on from its first frame, never off on the way (seen: ${JSON.stringify(r.states)})`);
      }
    }
    // ---- the arena page's compact box: an agent door (the full line, SNAP.md explained), then no door
    await setDoor({ door: 'Claude', route: 'plan', identity: 'Claude Code', keyMask: '' }, null);
    await p.goto(base + '/web/arena.html?ws=' + encodeURIComponent(ws));
    const ag = await firstSecond('[data-chat]');
    ok(ag.states.length === 1 && ag.states[0] === 'door:agent-door | ' + AGENT_ARENA, `arena.html, agent door: the compact block says "${AGENT_ARENA}" from its first frame (seen: ${JSON.stringify(ag.states)})`);
    await p.waitForFunction(() => !document.getElementById('order-mini').hidden, null, { timeout: 30000 }).catch(() => {});
    await p.screenshot({ path: path.join(OUT, 'arena-agent-door.png') });
    await setDoor(null, null);
    await p.goto(base + '/web/arena.html?ws=' + encodeURIComponent(ws));
    const a = await firstSecond('[data-chat]');
    fs.writeFileSync(path.join(OUT, 'box-arena-no-door.json'), JSON.stringify(a.log, null, 1));
    ok(a.states.length === 1 && a.states[0] === 'door:no-door | ' + NO_DOOR_ARENA, `arena.html, no door: the compact block's first second (from ${a.at} ms) shows one state, "${NO_DOOR_ARENA}" (seen: ${JSON.stringify(a.states)})`);
    const an = await noForm();
    ok(!an.input && !an.counter && !an.send && an.heading === 'Orders', `arena.html, no door: no text box, counter or Send, only "Orders" and the line`);
    await p.waitForFunction(() => !document.getElementById('order-mini').hidden, null, { timeout: 30000 }).catch(() => {});
    await p.screenshot({ path: path.join(OUT, 'arena-no-door.png') });
    const alb = await linkBox(p, '#order-mini a');
    ok(alb && alb.h >= 44 && alb.onScreen, `arena.html, no door: the link is on screen and its box is ${alb && alb.h} px tall (≥ 44)`);
    await Promise.all([p.waitForURL(/snapin\/index\.html\?step=doors/), p.evaluate(() => document.querySelector('#order-mini a').click())]); await ready();
    const av = await p.evaluate(() => ({ step: Snapin.view.step, mode: Snapin.view.mode }));
    ok(av.mode === 'flow' && av.step === 'doors' && /ws=/.test(p.url()), `arena.html, no door: the link opens the guide's AI step with the arena's ws (${p.url().replace(base, '').slice(0, 80)}…: step ${av.step})`);
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.slice(0, 3).join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 400)); try { await p.screenshot({ path: path.join(OUT, 'crash.png'), fullPage: true }); } catch (e2) { /* gone */ } }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  console.log(`${pass} passed, ${fail} failed; frames in ${OUT}`);
  process.exit(fail ? 1 : 0);
})();
