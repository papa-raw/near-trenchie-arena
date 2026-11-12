// The call to action's reserved space against board 2's HUD, in a real browser at 1440 and 390. Since board 2, the last
// .ha-layer in #world is the HP candle layer (hud.mjs), not the leaderboard cards, so the placement was reserving the
// candles that ride the fighters (the button dodged moving bodies) and only reached the leaderboards through the generic
// [data-panel] query. Checks, at each width on the live dev arena: the reserved set holds board 2's wall sign (both
// leaderboards); it holds no HP candle; "Snap in your trenchie" with Satrenchi's line overlaps neither leaderboard, at
// the first look and again 30 s later, while the fight runs; it keeps one spot through the fight (sampled every 3 s for
// 30 s: 0 px of movement); on a phone the feed's box never exceeds its cap (feed.mjs PHONE_MAX, 176 px), which is
// exactly what the button reserves above it. Frames go to <out-dir>.
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/cta_reserve_case.cjs [out-dir]
'use strict';
const fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const NEAR = path.resolve(__dirname, '..', '..', '..'), OUT = process.argv[2] || path.join(os.tmpdir(), 'snapin-cta-reserve');
fs.mkdirSync(OUT, { recursive: true });
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const HOSTS = require('./hosts.cjs');
const start = (args, ready) => HOSTS.start(args, ready, path.dirname(NEAR));

(async () => {
  const arenaPort = 20000 + Math.floor(Math.random() * 20000);
  await start(['near/arena/snap_local.py', '--port', String(arenaPort)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', 'http://127.0.0.1:' + arenaPort], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m, ws = 'ws://127.0.0.1:' + arenaPort;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  p.setDefaultTimeout(120000);
  const look = () => p.evaluate(() => {
    const a = document.getElementById('snapin-cta'), r = a.getBoundingClientRect(), R = (q) => ({ left: q.left, top: q.top, right: q.right, bottom: q.bottom });
    const hit = (q) => !(q.right <= r.left || q.left >= r.right || q.bottom <= r.top || q.top >= r.bottom);
    const sign = document.querySelector('.wallsign'), boards = sign ? [...sign.querySelectorAll('.board, section, ul')].filter((e) => e.getBoundingClientRect().width > 0) : [];
    const same = (u, v) => Math.abs(u.left - v.left) < 0.5 && Math.abs(u.top - v.top) < 0.5 && Math.abs(u.right - v.right) < 0.5 && Math.abs(u.bottom - v.bottom) < 0.5;
    const reserved = window.__ctaReserved ? window.__ctaReserved() : [];
    const candles = [...document.querySelectorAll('#world .ha-candle > *')].map((e) => R(e.getBoundingClientRect())).filter((q) => q.right > q.left && q.bottom > q.top);
    return { cta: [r.left, r.top, r.right, r.bottom].map(Math.round), x: a.style.getPropertyValue('--cta-x'), y: a.style.getPropertyValue('--cta-y'),
      sign: sign ? [sign.getBoundingClientRect().left, sign.getBoundingClientRect().top, sign.getBoundingClientRect().right, sign.getBoundingClientRect().bottom].map(Math.round) : null,
      onSign: !!sign && hit(sign.getBoundingClientRect()), onBoards: boards.filter((e) => hit(e.getBoundingClientRect())).length, boards: boards.length,
      signReserved: !!sign && reserved.some((q) => same(q, R(sign.getBoundingClientRect()))), hook: !!window.__ctaReserved,
      feedH: (() => { const f = document.querySelector('#world [data-panel="feed"]'); return f ? Math.round(f.getBoundingClientRect().height) : null; })(),
      feedReserve: (() => { const f = document.querySelector('#world [data-panel="feed"]'); return f ? f.dataset.reserve || '' : null; })(),
      candles: candles.length, candlesReserved: reserved.filter((q) => candles.some((c) => same(q, c))).length };
  });
  try {
    for (const W of [1440, 390]) {
      await p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
      await p.goto(base + '/web/arena.html?ws=' + encodeURIComponent(ws), { waitUntil: 'load' });
      await p.waitForFunction(() => { const w = document.getElementById('world'); return document.getElementById('status').className === 'live' && w.querySelector('[data-panel="board"]') && w.querySelector('[data-panel="btn1"]') && document.querySelectorAll('#world .ha-candle > *').length > 0; }, null, { timeout: 240000 });
      await sleep(3000);
      const g0 = await look();
      await p.screenshot({ path: path.join(OUT, 'cta-reserve-' + W + '.png'), timeout: 120000 });
      ok(g0.hook && g0.signReserved, `${W}: the reserved set holds the wall sign (both leaderboards) ${JSON.stringify(g0.sign)}`);
      ok(g0.candles > 0 && g0.candlesReserved === 0, `${W}: no HP candle is reserved (${g0.candles} candles on screen, ${g0.candlesReserved} reserved)`);
      ok(!g0.onSign && g0.onBoards === 0, `${W}: the call to action ${JSON.stringify(g0.cta)} overlaps neither leaderboard`);
      const spots = new Set([g0.x + ',' + g0.y]), heights = [g0.feedH];
      let g1 = g0;
      for (let t = 0; t < 10; t++) { await sleep(3000); g1 = await look(); spots.add(g1.x + ',' + g1.y); heights.push(g1.feedH); }
      ok(!g1.onSign && g1.onBoards === 0, `${W}: 30 s into the fight it still overlaps neither leaderboard ${JSON.stringify(g1.cta)}`);
      ok(spots.size === 1, `${W}: one spot through 30 s of fight, 11 samples (${[...spots].join(' | ')})`);
      if (W < 600) ok(g0.feedReserve === '176' && Math.max(...heights) <= 176, `${W}: the feed box stays within its 176 px cap (heights ${heights.join(', ')}; reserve ${g0.feedReserve})`);
    }
  } catch (e) { fail++; console.log('FAIL', String(e).slice(0, 300)); }
  await b.close();
  const left = await HOSTS.finish(); ok(left.length === 0, 'no host this case started survives it');
  console.log(`cta-reserve case: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
