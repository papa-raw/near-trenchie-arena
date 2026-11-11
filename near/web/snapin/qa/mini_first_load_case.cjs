// A review finding on ef87abe: on first load of arena.html the compact order box must not show before the placement
// finder has run against a HUD whose panels have all arrived and a ring that held still, and picked the same spot twice. At 390 (a phone never gets the box) it is never visible at
// all; at 1440 it first shows only after the HUD's feed is drawn, and at every moment it is visible it sits where it
// ends up and clear of the ring. Sampled every animation frame and on every change of the box, from the page's first
// script, from each load until 3 s after the HUD has drawn (at 1440, until 3 s after the box has decided). The fighter is a real DEV join; the player AI is the chat case's labelled stand-in.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/mini_first_load_case.cjs
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
// a stand-in player AI that takes orders (so the page wants the box), labelled; only where ?stubbrain is set
const STUB = () => {
  if (!/stubbrain/.test(location.search)) return;
  window.SnapBrain = { stub: true, on(fn) { fn({ state: 'driving', chip: 'stand-in', conversation: [] }); return () => {}; }, async tell() { return { reply: { text: 'ok' }, receipt: { status: 'applied', summary: 'ok' } }; } };
};
// the recorder: every frame and every change of #order-mini, from the first script on
const REC = () => {
  if (!/arena\.html/.test(location.pathname)) return;
  const t0 = performance.now(), S = window.__miniSamples = [];
  const sample = (why) => {
    const box = document.getElementById('order-mini'); if (!box) return;
    const cs = getComputedStyle(box), r = box.getBoundingClientRect();
    const visible = !box.hidden && cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0;
    const feed = document.querySelector('#world [data-panel="feed"]'), fr = feed && feed.getBoundingClientRect();
    S.push({ t: Math.round(performance.now() - t0), why, visible, rect: [r.left, r.top, r.width, r.height].map(Math.round), feed: !!(fr && fr.width > 0 && fr.height > 0) });
  };
  const frame = () => { sample('frame'); requestAnimationFrame(frame); }; requestAnimationFrame(frame);
  const watch = () => new MutationObserver((ms) => { if (ms.some((m) => m.target.id === 'order-mini' || [].some.call(m.addedNodes, (n) => n.id === 'order-mini'))) sample('change'); })
    .observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['hidden', 'style', 'class'] });
  if (document.documentElement) watch(); else document.addEventListener('readystatechange', watch, { once: true });
};
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m, ws = 'ws://127.0.0.1:' + port;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const ctx = await b.newContext();
  await ctx.addInitScript(STUB); await ctx.addInitScript(REC);
  await ctx.route('**/web/snapin/brain.js', (r) => r.fulfill({ status: 200, contentType: 'text/javascript', body: '/* mini_first_load_case: brain.js withheld; the case stands in for SnapBrain.tell where ?stubbrain is set */' }));
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  try {
    await p.goto(base + '/web/snapin/index.html?step=wallet&ws=' + encodeURIComponent(ws)); await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
    const joined = await p.evaluate(async () => { try { await SnapRoom.join({ name: 'minipip', preset: 'survivor-beam', termsVersion: '1' }); return SnapRoom.status().phase; } catch (e) { return 'ERR ' + e.message; } });
    ok(joined === 'in', `a real DEV fighter is in the ring (${joined})`);
    for (const W of [390, 1440, 390]) {
      await p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
      await p.goto(base + '/web/arena.html?stubbrain=1&ws=' + encodeURIComponent(ws));
      // assert only once the HUD has drawn (slow in headless WebGL) and the finder has had 3 s more to decide
      const drew = await p.waitForFunction(() => { const f = document.querySelector('#world [data-panel="feed"]'), r = f && f.getBoundingClientRect(); return !!(r && r.width > 0 && r.height > 0); }, null, { timeout: 60000 }).then(() => true, () => false);
      // and, at 1440, until the box says it has decided (data-wait empty: HUD arrived, ring still, same spot twice)
      const decided = W < 600 ? true : await p.waitForFunction(() => { const x = document.getElementById('order-mini'); return !!(x && x.dataset.wait === ''); }, null, { timeout: 60000 }).then(() => true, () => false);
      await sleep(3000);
      const res = await p.evaluate(() => {
        const S = window.__miniSamples || [], box = document.getElementById('order-mini'), ring = window.__arenaRingOutline ? window.__arenaRingOutline() : null;
        const inPoly = (x, y) => { let c = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) { const a = ring[i], b = ring[j]; if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) c = !c; } return c; };
        const overRing = (r) => { if (!ring) return true; const [x, y, w, h] = r; return [[x, y], [x + w, y], [x, y + h], [x + w, y + h], [x + w / 2, y], [x + w / 2, y + h], [x, y + h / 2], [x + w, y + h / 2]].some((c) => inPoly(c[0], c[1])) || ring.some((q) => q[0] > x && q[0] < x + w && q[1] > y && q[1] < y + h); };
        const fr = box && box.getBoundingClientRect(), final = box && !box.hidden ? [fr.left, fr.top, fr.width, fr.height].map(Math.round) : null;
        const vis = S.filter((s) => s.visible);
        return { drew: true, n: S.length, made: !!box, final, vis: vis.length, firstVis: vis[0] || null, earlyVis: vis.filter((s) => !s.feed).length, over: vis.filter((s) => overRing(s.rect)).length,
          moved: final ? vis.filter((s) => s.rect.some((v, i) => Math.abs(v - final[i]) > 2)).length : vis.length, cue: document.getElementById('snapin-cta').innerText.replace(/\s+/g, ' ').trim(), wait: box && box.dataset.wait, ringNow: ring ? ring.length : 0, panels: [...document.querySelectorAll('#world [data-panel]')].map((e) => e.dataset.panel).join(','), lastVis: vis[vis.length - 1] || null };
      });
      console.log('  info', W, JSON.stringify({ wait: res.wait, ringNow: res.ringNow, final: res.final, firstVis: res.firstVis, lastVis: res.lastVis, panels: res.panels, cue: res.cue.slice(0, 120) }));
      if (W < 600) {
        ok(drew && res.made && res.n > 20 && res.vis === 0 && /Give orders in Your trenchie/.test(res.cue),
          `390: in ${res.n} samples from first load until 3 s after the HUD drew the compact box is never visible (visible in ${res.vis}${res.firstVis ? ', first at ' + res.firstVis.t + ' ms' : ''}), and the cue says "${(res.cue.match(/Give orders[^.]*\./) || [res.cue.slice(0, 60)])[0]}"`);
      } else {
        ok(drew && decided && res.made && res.final && res.vis > 0 && res.earlyVis === 0 && res.over === 0 && res.moved === 0,
          `1440: the box decides (${decided ? 'yes' : 'never: ' + res.wait}) and first shows at ${res.firstVis ? res.firstVis.t + ' ms' : 'never'}, after the HUD's feed is drawn (${res.earlyVis} visible samples before it); in all ${res.vis} visible samples it is at its final place ${JSON.stringify(res.final)} (${res.moved} elsewhere) and clear of the ring (${res.over} over it)`);
      }
    }
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
