// Owner chat case: the owner's order box beside the persona in the ring view, in a real browser at 1440 and 390.
// A visitor snaps in through the guide (DEV arena, real join). Then:
//  1. with no player AI on the page, the box is off and says why;
//  2. with a player AI that takes orders, an order typed and sent with Enter shows the trenchie's in-character reply and the
//     host's receipt verbatim in a quiet mono line; a refused order shows its fixes; Shift+Enter breaks a line; an empty
//     order cannot be sent; 300 characters at most; focus and the caret stay in the box across a re-render; keyboard rings;
//     beside the card at 1440, stacked at 390, no overlap and no sideways scroll; console clean.
// The player AI here is a stand-in supplied by this case (SnapBrain.tell had not landed when this case was written):
// it answers in the agreed shape {reply:{text}, receipt:{state, summary, tick, fixes}} and says so in the output.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/chat_case.cjs [out-dir]
'use strict';
const { spawn } = require('child_process'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..'), OUT = process.argv[2] || path.join(os.tmpdir(), 'snapin-chat');
fs.mkdirSync(OUT, { recursive: true });
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
// the stand-in player AI, installed before the page's scripts when ?stubbrain is in the URL
const ACKS = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'bm-a-acks.json'), 'utf8'));
const STUB = (ACKS) => {
  if (!/stubbrain/.test(location.search)) return;
  const subs = [], st = { state: 'driving', chip: 'Your AI drives your trenchie.', conversation: [] };
  window.SnapBrain = {
    stub: true,
    on(fn) { subs.push(fn); fn(st); return () => {}; },
    async tell(text) {
      await new Promise((r) => setTimeout(r, 300));
      st.conversation.push({ who: 'owner', text, at: Date.now() });
      let r;
      // the engine's real ack() outputs (qa/fixtures/bm-a-acks.json), handed over exactly as the host would sign them
      if (/hp_low|refuse/i.test(text)) r = { reply: { text: 'Hp low? Never heard of it, boss.', voice: true }, receipt: ACKS.refused };
      else if (/clip/i.test(text)) r = { reply: { text: 'Fine, I will keep it smaller.', voice: true }, receipt: ACKS.clipped };
      else r = { reply: { text: 'On it! Loot first, then the chase, and I bail out when I am hurt.', voice: true }, receipt: ACKS.four_reflex };
      st.conversation.push({ who: 'trenchie', text: r.reply.text, at: Date.now() }, { who: 'host', receipt: r.receipt, at: Date.now() });
      subs.forEach((f) => f(st));
      return r;
    }
  };
};

(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m, ws = 'ws://127.0.0.1:' + port;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const ctx = await b.newContext();
  await ctx.addInitScript(STUB, ACKS);
  // brain.js (on main now) has no tell() yet and would replace the stand-in: this case serves it empty, labelled
  await ctx.route('**/web/snapin/brain.js', (r) => r.fulfill({ status: 200, contentType: 'text/javascript', body: '/* chat_case: brain.js withheld; the case stands in for SnapBrain.tell where ?stubbrain is set */' }));
  await ctx.addInitScript(() => { const r = window.requestAnimationFrame.bind(window); window.requestAnimationFrame = (cb) => (window.__freeze ? 0 : r(cb)); });
  await ctx.route('https://cloud-api.near.ai/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ id: 't', object: 'chat.completion', choices: [{ index: 0, message: { role: 'assistant', content: 'Ready.' }, finish_reason: 'stop' }], usage: { prompt_tokens: 9, completion_tokens: 2 } }) }));
  const p = await ctx.newPage(); const errs = [];
  p.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.text().slice(0, 200) + ' @ ' + p.url().replace(base, '')); });
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  p.on('response', (r) => { if (r.status() >= 400 && !/cloud-api\.near\.ai/.test(r.url())) errs.push('http ' + r.status() + ' ' + r.url().replace(/^https?:\/\/[^/]+/, '')); });
  const ready = () => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
  const click = async (act) => { await p.click(`[data-act="${act}"]`); await sleep(150); };
  try {
    await p.setViewportSize({ width: 1440, height: 900 });
    // ---- snap in (real DEV join)
    await p.goto(base + '/web/snapin/index.html?step=wallet&ws=' + encodeURIComponent(ws)); await ready();
    await click('wallet-dev'); await click('preset:Survivor Beam'); await click('claim');
    await p.fill('#name', 'Chatpip'); await click('step:doors');
    await click('ai:door:NEAR AI Cloud'); await p.fill('#key', 'sk-test-player-key'); await click('ai:test');
    await p.waitForFunction(() => SnapDoors.state.state === 'connected', null, { timeout: 20000 }); await click('ai:continue');
    await p.waitForFunction(() => Snapin.view.terms && Snapin.view.terms.version, null, { timeout: 20000 });
    for (const id of ['#agree-ai', '#agree-public', '#agree-gear']) await p.check(id);
    await click('agree');
    await p.waitForFunction(() => SnapRoom.status().phase === 'in', null, { timeout: 90000 }); await sleep(800);
    // ---- 1. no player AI on this page: the box is off and says why
    const off = await p.evaluate(() => ({ disabled: document.querySelector('#order').disabled, text: document.querySelector('[data-chat]').innerText }));
    ok(off.disabled && /can’t take orders on this page: its AI is not loaded here/.test(off.text), `with no player AI loaded, the box is off and says why: "${(off.text.match(/Your trenchie can’t[^\n]*/) || [''])[0]}"`);
    await p.screenshot({ path: path.join(OUT, 'chat-off-1440.png'), fullPage: true });
    // ---- 2. with a player AI that takes orders (the case's stand-in)
    for (const W of [1440, 390]) {
      await p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
      await p.goto(base + '/web/snapin/index.html?step=ring&stubbrain=1&ws=' + encodeURIComponent(ws)); await ready();
      await p.waitForFunction(() => SnapRoom.status().phase === 'in' && document.querySelector('#order') && !document.querySelector('#order').disabled, null, { timeout: 30000 });
      ok(await p.evaluate(() => window.SnapBrain.stub === true), `${W}: the player AI on this page is the case's stand-in (SnapBrain.tell is not landed)`);
      // layout: beside the card at 1440, stacked at 390; no overlap; no sideways scroll
      const lay = await p.evaluate(() => {
        const card = document.querySelector('.ring-split > div:first-child').getBoundingClientRect(), box = document.querySelector('[data-chat]').getBoundingClientRect();
        const hit = !(card.right <= box.left || box.right <= card.left || card.bottom <= box.top || box.bottom <= card.top);
        return { side: box.left >= card.right - 1, below: box.top >= card.bottom - 1, hit, sw: document.documentElement.scrollWidth, w: innerWidth };
      });
      ok(!lay.hit && (W > 700 ? lay.side : lay.below) && lay.sw <= lay.w, `${W}: the order box sits ${W > 700 ? 'beside' : 'below'} the persona card, no overlap, no sideways scroll (${JSON.stringify(lay)})`);
      // an empty order cannot be sent
      ok(await p.$eval('.chat-send', (e) => e.disabled), `${W}: Send is off while the box is empty`);
      // keyboard: Tab from the box reaches Send with a ring; Shift+Enter breaks a line, Enter sends
      await p.focus('#order'); await p.keyboard.type('Guard the bell'); await p.keyboard.press('Shift+Enter'); await p.keyboard.type('and stay near it');
      ok((await p.inputValue('#order')) === 'Guard the bell\nand stay near it', `${W}: Shift+Enter breaks a line instead of sending`);
      // focus and caret survive a re-render (a status change while typing)
      await p.evaluate(() => { const t = document.querySelector('#order'); t.setSelectionRange(5, 5); Snapin.render(); });
      const kept = await p.evaluate(() => ({ id: document.activeElement.id, at: document.activeElement.selectionStart, v: document.activeElement.value }));
      ok(kept.id === 'order' && kept.at === 5 && kept.v === 'Guard the bell\nand stay near it', `${W}: focus, caret and the draft survive a re-render (${JSON.stringify(kept)})`);
      await p.keyboard.press('End'); await p.keyboard.press('Tab');
      const ring = await p.evaluate(() => { const e = document.activeElement, s = getComputedStyle(e); return (e.dataset.act || e.id) + ':' + (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2); });
      ok(/^chat-send:true$/.test(ring), `${W}: Tab reaches Send with a focus ring (${ring})`);
      await p.focus('#order'); await p.keyboard.press('Enter');
      await p.waitForFunction(() => /Loot first/.test(document.querySelector('[data-chat]').innerText), null, { timeout: 10000 });
      const sent = await p.evaluate(() => ({ reply: document.querySelector('.chat-reply').textContent, receipt: document.querySelector('.chat-receipt').textContent, font: getComputedStyle(document.querySelector('.chat-receipt')).fontFamily, draft: document.querySelector('#order').value, focus: document.activeElement && document.activeElement.id }));
      ok(sent.receipt === ACKS.four_reflex.summary && /Space Mono/.test(sent.font) && sent.draft === '' && /^“On it! Loot first/.test(sent.reply), `${W}: Enter sends; the receipt is the engine's ack.summary byte for byte, in mono (${sent.receipt.length} chars)`);
      ok(sent.focus === 'order', `${W}: after an Enter send, focus is back in the order box (${sent.focus})`);
      // a mouse send keeps focus in the box too
      await p.fill('#order', 'Clip this plan'); await p.dispatchEvent('#order', 'input');
      const sb = await p.$eval('.chat-send', (e) => { const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, cls: e.className }; });
      await p.mouse.click(sb.x, sb.y);
      await p.waitForFunction(() => /keep it smaller/.test(document.querySelector('[data-chat]').innerText), null, { timeout: 10000 });
      const cl = await p.evaluate(() => ({ focus: document.activeElement && document.activeElement.id, receipt: document.querySelector('.chat-receipt').textContent, fixes: [...document.querySelectorAll('.chat-fixes li')].map((x) => x.textContent) }));
      ok(cl.focus === 'order', `${W}: after a mouse send, focus is back in the order box (${cl.focus})`);
      ok(cl.receipt === ACKS.clipped.summary && JSON.stringify(cl.fixes) === JSON.stringify(ACKS.clipped.clipped.slice(1).map((x) => x.fix)), `${W}: a clipped plan shows its summary verbatim and only the fixes after the first (${JSON.stringify(cl.fixes)})`);
      ok(!/main-action/.test(sb.cls) && !/bell/i.test(await p.getAttribute('#order', 'placeholder')), `${W}: Send is a secondary action (one gold action a screen) and the placeholder names nothing that is not on the island`);
      await p.screenshot({ path: path.join(OUT, `chat-applied-${W}.png`), fullPage: true });
      // a refused order shows its fixes
      await p.fill('#order', 'Refuse me: if hp_low then say x'); await p.dispatchEvent('#order', 'input'); await click('chat-send');
      await p.waitForFunction(() => /Never heard of it/.test(document.querySelector('[data-chat]').innerText), null, { timeout: 10000 });
      const ref = await p.evaluate(() => ({ receipt: document.querySelector('.chat-receipt').textContent, fixes: [...document.querySelectorAll('#order-state .chat-fixes li')].map((x) => x.textContent), text: document.querySelector('[data-chat]').innerText, cls: document.querySelector('.chat-receipt').className }));
      const wantFixes = [].concat(ACKS.refused.refused || [], ACKS.refused.clipped || []).map((x) => x.fix).slice(1);
      ok(ref.receipt === ACKS.refused.summary && !/Refused: Refused/.test(ref.text) && JSON.stringify(ref.fixes) === JSON.stringify(wantFixes) && /refused/.test(ref.cls), `${W}: a refused order shows the engine's summary verbatim (its fix inside it), no doubled "Refused:", only the fixes after the first (${JSON.stringify(ref.fixes)}): "${ref.receipt.slice(0, 80)}…"` + (ref.receipt === ACKS.refused.summary ? '' : ' [got ' + ref.receipt.length + ' chars vs ' + ACKS.refused.summary.length + ']') + ' fixes=' + ref.fixes.length + ' cls=' + ref.cls + ' doubled=' + /Refused: Refused/.test(ref.text));
      const nturns = await p.evaluate(() => [...document.querySelectorAll('.chat-turns > li')].map((x) => x.className + ':' + x.textContent.slice(0, 24)));
      ok(nturns.length === 6, `${W}: the recent turns list shows the two earlier exchanges (6 turns), not the latest again (${nturns.length}: ${JSON.stringify(nturns).slice(0, 300)})`);
      // 300 characters at most
      await p.fill('#order', 'x'.repeat(320));
      ok((await p.inputValue('#order')).length === 300 && /300 \/ 300/.test(await p.innerText('#order-count')), `${W}: an order is at most 300 characters (counter reads 300 / 300)`);
      await p.screenshot({ path: path.join(OUT, `chat-refused-${W}.png`), fullPage: true });
      // ---- the compact box on the live arena page, for the player's own fighter
      await p.goto(base + '/web/arena.html?stubbrain=1&ws=' + encodeURIComponent(ws));
      await p.waitForFunction(() => document.getElementById('status').className === 'live' && document.querySelector('#world [data-panel="feed"]'), null, { timeout: 150000 });
      await p.waitForFunction(() => window.SnapRoom && SnapRoom.status().phase === 'in' && document.getElementById('order-mini'), null, { timeout: 60000 });
      // the box shows only once the finder has settled (HUD arrived, ring still, the same spot twice); a phone never gets it
      await p.waitForFunction(() => innerWidth < 600 || document.getElementById('order-mini').dataset.wait === '', null, { timeout: 60000 }).catch(() => {});
      await sleep(1500);
      const m = await p.evaluate(() => {
        const box = document.getElementById('order-mini'), cta = document.getElementById('snapin-cta').getBoundingClientRect(), shown = !box.hidden, r = box.getBoundingClientRect();
        const world = document.getElementById('world'), layers = [...world.children].filter((c) => c.classList.contains('ha-layer'));
        const hud = [...world.querySelectorAll('[data-panel]:not([data-kind="world"])'), ...(layers.length ? layers[layers.length - 1].children : []), ...document.querySelectorAll('.collabel, .inset:not([hidden])')].map((e) => e.getBoundingClientRect()).filter((q) => q.width && q.height);
        const hit = (q) => !(q.right <= r.left || q.left >= r.right || q.bottom <= r.top || q.top >= r.bottom);
        return { shown, inView: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight, hud: hud.filter(hit).length, cta: hit(cta), cue: document.querySelector('#snapin-cta .cue').textContent, r: [r.left, r.top, r.right, r.bottom].map(Math.round) };
      });
      const ringHit = () => p.evaluate(() => {
        const box = document.getElementById('order-mini'); if (box.hidden) return { hidden: true };
        const r = box.getBoundingClientRect(), ring = window.__arenaRingOutline();
        const inPoly = (x, y) => { let c = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) { const a = ring[i], b = ring[j]; if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) c = !c; } return c; };
        const pts = []; for (let i = 0; i <= 10; i++) for (let k = 0; k <= 10; k++) pts.push([r.left + r.width * i / 10, r.top + r.height * k / 10]);
        return { hidden: false, h: Math.round(r.height), cover: Math.round(100 * r.width * r.height / (innerWidth * innerHeight)), overRing: pts.some((q) => inPoly(q[0], q[1])) || ring.some((q) => q[0] > r.left && q[0] < r.right && q[1] > r.top && q[1] < r.bottom) };
      });
      if (m.shown) {
        ok(m.inView && m.hud === 0 && !m.cta, `${W}: arena page: the compact order box is shown, clear of the HUD and the call to action (${JSON.stringify(m.r)})`);
        await p.fill('#order-mini #order', 'Loot and run'); await p.focus('#order-mini #order'); await p.keyboard.press('Enter');
        await p.waitForFunction(() => /Loot first/.test(document.getElementById('order-mini').innerText), null, { timeout: 10000 }).catch(() => {});
        await sleep(1200);
        const after = await ringHit(), fold = await p.evaluate(() => ({ receipt: document.querySelector('#order-mini .chat-receipt').textContent, folded: document.querySelector('#order-mini .chat-receipt').classList.contains('folded'), more: !!document.querySelector('#order-mini .chat-more'), focus: document.activeElement && document.activeElement.id }));
        ok(fold.receipt === ACKS.four_reflex.summary && fold.folded && fold.more && fold.focus === 'order', `${W}: on the arena page the reply and the receipt (verbatim) show folded to one line with More, focus kept in the box`);
        ok(after.hidden || (after.h <= 168 && !after.overRing), `${W}: with the engine's real 4-reflex receipt the box is ${after.hidden ? 'hidden (no free spot)' : after.h + ' px tall (cap 168), ' + after.cover + '% of the screen, never over the ring'}`);
      } else {
        ok(/Give orders in Your trenchie/.test(m.cue), `${W}: arena page: a phone never gets the compact box; Satrenchi points to Your trenchie ("${m.cue}")`);
      }
      await p.evaluate(() => { window.__freeze = true; }).catch(() => {}); await sleep(250);
      await p.screenshot({ path: path.join(OUT, `arena-order-${W}.png`), timeout: 30000 }).catch(() => {});
    }
    // brain.js and emoji-set.js are other lanes' optional files, not on this branch: their 404s (and only theirs) are set aside
    const optional404 = errs.filter((e) => /^http 404 \/web\/snapin\/(brain|emoji-set)\.js$/.test(e)).length;
    const own = errs.filter((e) => !/GL Driver/.test(e) && !/^http 404 \/web\/snapin\/(brain|emoji-set)\.js$/.test(e) && !/Refused to execute script from '[^']*\/web\/snapin\/(brain|emoji-set)\.js'/.test(e)).filter((e) => !(optional404 && /status of 404/.test(e)));
    ok(own.length === 0, `console clean (set aside: ${optional404} 404s of the optional brain.js / emoji-set.js)` + (own.length ? ': ' + own.slice(0, 4).join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 400)); try { await p.screenshot({ path: path.join(OUT, 'crash.png'), fullPage: true }); } catch (e2) { /* gone */ } }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  console.log(`${pass} passed, ${fail} failed; frames in ${OUT}`);
  process.exit(fail ? 1 : 0);
})();
