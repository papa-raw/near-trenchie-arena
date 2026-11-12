// W18 case: the live arena's "Snap in your trenchie" call to action, in a real browser at 1440 and 390.
// Starts its own DEV arena (near/arena/snap_local.py) and the one-origin DEV server (snapin/serve.py) on free loopback ports,
// then: the button and Satrenchi's cue are on screen, unclipped and clear of the fixed HUD; Tab reaches it with a visible
// focus ring; Enter opens the guide at the wallet step with the arena's address carried; "Keep watching", × and Escape
// return to the live page; the browser's Back returns to the guide; both consoles stay clean. Frames go to <out-dir>.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/cta_case.cjs [out-dir]
'use strict';
const { spawn } = require('child_process'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const NEAR = path.resolve(__dirname, '..', '..', '..'), OUT = process.argv[2] || path.join(os.tmpdir(), 'snapin-cta');
fs.mkdirSync(OUT, { recursive: true });
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || path.dirname(NEAR));

(async () => {
  const arenaPort = 20000 + Math.floor(Math.random() * 20000);
  const arena = await start(['near/arena/snap_local.py', '--port', String(arenaPort)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', 'http://127.0.0.1:' + arenaPort], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m, ws = 'ws://127.0.0.1:' + arenaPort;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  // the arena draws every frame; a capture needs the frame loop held still for a moment
  await ctx.addInitScript(() => { const r = window.requestAnimationFrame.bind(window); window.requestAnimationFrame = (cb) => (window.__freeze ? 0 : r(cb)); });
  const p = await ctx.newPage(); const errs = [];
  // a loaded machine: the arena's software-GL frames can drop to about one a second; give every wait room, and hold the
  // frame loop still (window.__freeze) before keyboard and pointer actions so Playwright's stability check is not starved
  p.setDefaultTimeout(90000); p.setDefaultNavigationTimeout(90000);
  const still = async () => { await p.evaluate(() => { window.__freeze = true; }); await sleep(250); };
  p.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.type() + ': ' + m.text() + ' @ ' + p.url()); });
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  const shot = async (name) => { await p.evaluate(() => { window.__freeze = true; }); await sleep(250); await p.screenshot({ path: path.join(OUT, name + '.png'), timeout: 60000 }); await p.evaluate(() => { window.__freeze = false; }); };
  const live = async () => { await p.waitForFunction(() => document.getElementById('status').className === 'live', null, { timeout: 45000 }); await p.waitForFunction(() => { const w = document.getElementById('world'); return w.querySelector('[data-panel="feed"]') && w.querySelector('[data-panel="btn1"]') && w.querySelector('[data-panel="board"]'); }, null, { timeout: 150000 }); await sleep(2500); };
  const guide = () => p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 });
  try {
    for (const W of [1440, 390]) {
      await p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
      await p.goto(base + '/web/arena.html?ws=' + encodeURIComponent(ws), { waitUntil: 'load' }); await live();
      const g = await p.evaluate(() => {
        const a = document.getElementById('snapin-cta'), r = a.getBoundingClientRect(), img = a.querySelector('img');
        const hit = (q) => !(q.right <= r.left || q.left >= r.right || q.bottom <= r.top || q.top >= r.bottom);
        // the fixed HUD: the panel host (banner, sound, menu, feed), the leaderboard cards, their labels, the follow view, the status pill
        const world = document.getElementById('world'), layers = [...world.children].filter((c) => c.classList.contains('ha-layer'));
        const fixed = [...world.querySelectorAll('[data-panel]:not([data-kind="world"])'), ...layers[layers.length - 1].children, ...document.querySelectorAll('.collabel, .inset:not([hidden]), #status:not(.live)')]
          .filter((e) => { const q = e.getBoundingClientRect(); return q.width > 0 && q.height > 0 && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none'; });
        const clippedEls = [...a.querySelectorAll('.go, .cue')].filter((e) => e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1), clipped = clippedEls.length;
        const boxes = [...a.querySelectorAll('.go, .cue')].map((e) => e.className + ' ' + e.scrollWidth + 'x' + e.scrollHeight + '/' + e.clientWidth + 'x' + e.clientHeight).join(', ');
        return { r: [r.left, r.top, r.right, r.bottom].map(Math.round), vw: innerWidth, vh: innerHeight, text: a.innerText.replace(/\s+/g, ' ').trim(), href: a.getAttribute('href'),
          img: img.complete && img.naturalWidth > 0, overlaps: fixed.filter((e) => hit(e.getBoundingClientRect())).map((e) => e.tagName + '.' + (e.getAttribute('class') || '') + JSON.stringify([e.getBoundingClientRect().left, e.getBoundingClientRect().top].map(Math.round))), hudCount: fixed.length, clipped,
          feed: (() => { const f = world.querySelector('[data-panel="feed"]').getBoundingClientRect(); return [f.left, f.top, f.right, f.bottom].map(Math.round); })(),
          boxes, onTop: document.elementFromPoint((r.left + r.right) / 2, r.bottom - 8)?.closest('#snapin-cta') === a };
      });
      ok(g.r[0] >= 0 && g.r[1] >= 0 && g.r[2] <= g.vw && g.r[3] <= g.vh, `${W}: the call to action is fully on screen ${JSON.stringify(g.r)}`);
      ok(/Snap in your trenchie/.test(g.text) && /Satrenchi/.test(g.text) && g.img, `${W}: button, Satrenchi's line and his still are there: "${g.text}"`);
      ok(g.hudCount > 0 && g.overlaps.length === 0, `${W}: clear of the fixed HUD, ${g.hudCount} pieces checked (${g.overlaps.join(', ') || 'no overlap'}); feed at ${JSON.stringify(g.feed)}`);
      // the worst case: the feed at its full size, drawn by the same HUD art offscreen at this width
      const worst = await p.evaluate(async () => {
        const W = innerWidth, H = innerHeight, host = document.createElement('div'); host.style.cssText = 'position:fixed;left:0;top:0;width:' + W + 'px;height:' + H + 'px;visibility:hidden;pointer-events:none';
        document.body.appendChild(host);
        const t = (s) => ({ tag: s, name: s, hex: '#88aa99' }), long = { kind: 'drop', a: t('Banana Zone'), b: t('Banana Zone'), item: 'Gershunode Gavel #12' };
        await window.HUDART.mount(host, { concept: 'candle', draft: 'a', w: W, h: H, fighters: [], feed: [long, long, long] });
        const f = host.querySelector('[data-panel="feed"]').getBoundingClientRect(), r = document.getElementById('snapin-cta').getBoundingClientRect();
        host.remove();
        return { feed: [f.left, f.top, f.right, f.bottom].map(Math.round), clear: f.right <= r.left || f.left >= r.right || f.bottom <= r.top || f.top >= r.bottom };
      }).catch((e) => ({ error: String(e).slice(0, 200) }));
      ok(worst.clear === true, `${W}: clear of a full feed too (3 long lines, 2 on a phone): ${JSON.stringify(worst)}`);
      ok(g.clipped === 0 && g.onTop, `${W}: no clipped text (scroll/client: ${g.boxes}), nothing drawn over the button`);
      ok(g.href.includes('step=wallet') && g.href.includes('ws=') && g.href.includes('from=arena'), `${W}: the link opens the guide at the wallet step with this arena's address: ${g.href}`);
      await shot(`w18-arena-${W}`);
      await still();
      // keyboard: Tab reaches it, with a visible ring
      let focused = false;
      for (let i = 0; i < 12 && !focused; i++) { await p.keyboard.press('Tab'); focused = await p.evaluate(() => document.activeElement && document.activeElement.id === 'snapin-cta'); }
      const ring = await p.evaluate(() => { const s = getComputedStyle(document.querySelector('#snapin-cta .go')); return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2; });
      ok(focused && ring, `${W}: Tab reaches the call to action and shows a focus ring`);
      await shot(`w18-arena-focus-${W}`);
      await Promise.all([p.waitForURL(/snapin\/index\.html/), p.keyboard.press('Enter')]); await guide(); await sleep(400);
      const w = await p.evaluate(() => ({ step: Snapin.view.step, h1: document.querySelector('h1') && document.querySelector('h1').textContent, url: location.search }));
      ok(w.step === 'wallet' && /Own your persona/.test(w.h1) && w.url.includes('ws='), `${W}: Enter opens the guide at the wallet step (${w.h1}; ${w.url})`);
      await shot(`w18-guide-wallet-${W}`);
      // back to watching, three ways
      await Promise.all([p.waitForURL(/arena\.html/), p.click('[data-act="step:watch"]')]);
      ok(p.url().includes('ws=' + encodeURIComponent(ws)) || p.url().includes('ws=' + ws), `${W}: "Keep watching" returns to the live arena on the same host`);
      await live(); await still();
      await Promise.all([p.waitForURL(/snapin\/index\.html/), p.goBack()]); await guide();
      ok(await p.evaluate(() => Snapin.view.step === 'wallet'), `${W}: the browser's Back from the arena returns to the guide's wallet step`);
      await Promise.all([p.waitForURL(/arena\.html/), p.click('[data-act="close"]')]);
      ok(true, `${W}: × returns to the live arena`);
      await live(); await still();
      await Promise.all([p.waitForURL(/snapin\/index\.html/), p.click('#snapin-cta')]); await guide();
      await Promise.all([p.waitForURL(/arena\.html/), p.keyboard.press('Escape')]);
      ok(true, `${W}: a click on the call to action opens the guide; Escape returns to the arena`);
      await live();
    }
    // headless Chromium's software GL logs "GPU stall due to ReadPixels" on the arena page as it stands on main too (no screenshot
    // needed, measured 2026-11-11): a driver note of the test browser, counted and printed, never mixed with the page's own messages
    const gl = errs.filter((e) => /GL Driver Message \(OpenGL, Performance, GL_CLOSE_PATH_NV, High\): GPU stall due to ReadPixels/.test(e)), own = errs.filter((e) => !gl.includes(e));
    ok(own.length === 0, `console clean on both pages at both widths (${gl.length} headless GL driver notes set aside)` + (own.length ? ': ' + own.slice(0, 4).join(' | ') : ''));
  } catch (e) {
    ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300));
    try { console.log('at', p.url(), await p.evaluate(() => (document.getElementById('status') || {}).textContent)); console.log(errs.slice(0, 6).join('\n')); await shot('crash'); } catch (e2) { /* page gone */ }
  }
  await b.close().catch(() => {});
  await fetch('http://127.0.0.1:' + arenaPort + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  web.child.kill(); arena.child.kill();
  fs.writeFileSync(path.join(OUT, 'cta-case.json'), JSON.stringify({ pass, fail, at: new Date().toISOString() }, null, 1));
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed; frames in ${OUT}`);
  process.exit(fail ? 1 : 0);
})();
