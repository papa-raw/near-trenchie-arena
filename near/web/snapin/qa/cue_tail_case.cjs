// Pat's note on the arena's call to action: the pointer on Satrenchi's cue bubble sat off the bubble's edge and did not
// line up with Satrenchi. In a real browser, at 1440 and 390, with the call to action forced into each of the five places
// the finder can pick (?ctaspot=0..4), this case checks the tail:
//  * it exists, and its base sits on the bubble's border, along the rounded bottom-left corner (the bubble is a pill);
//  * the join, read from the pixels of a 2x crop: the border is open (paper) in the middle of the opening, ink just past
//    each end of it, and the wedge's middle is paper: no gap, no border line across the tail;
//  * it points at Satrenchi's face (the hood opening, measured from the sprite): the tip-to-face direction is within 10
//    degrees of the tail's own direction; the tip is outside the bubble and does not reach into the face.
// Frames: cue-<W>-spot<N>.png (2x crops) in the out dir. The arena is the real DEV arena (snap_local.py through serve.py).
// usage: NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/snapin/qa/cue_tail_case.cjs [out-dir]
'use strict';
const { spawn } = require('child_process'), fs = require('fs'), path = require('path'), os = require('os');
const { chromium } = require('playwright');
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const OUT = process.argv[2] || path.join(os.tmpdir(), 'snapin-cue-tail'); fs.mkdirSync(OUT, { recursive: true });
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m); } else { fail++; console.log('FAIL', m); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// hosts start through the shared harness: each ends with this case however it ends (qa/hosts.cjs)
const HOSTS = require('./hosts.cjs');
const start = (args, ready, cwd) => HOSTS.start(args, ready, cwd || REPO);
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const base = 'http://127.0.0.1:' + web.m, ws = 'ws://127.0.0.1:' + port;
  const b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
  const ctx = await b.newContext({ deviceScaleFactor: 2 });
  await ctx.addInitScript(() => { const r = window.requestAnimationFrame.bind(window); window.requestAnimationFrame = (cb) => (window.__freeze ? 0 : r(cb)); });
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  try {
    for (const W of [1440, 390]) {
      await p.setViewportSize({ width: W, height: W > 700 ? 900 : 844 });
      for (let n = 0; n < 5; n++) {
        await p.goto(base + '/web/arena.html?ctaspot=' + n + '&ws=' + encodeURIComponent(ws));
        await p.waitForFunction(() => { const a = document.getElementById('snapin-cta'), i = a && a.querySelector('img'); return i && i.complete && i.naturalWidth > 0 && a.style.getPropertyValue('--cta-x'); }, null, { timeout: 60000 });
        await p.evaluate(() => document.fonts && document.fonts.ready); await sleep(1200);
        await p.evaluate(() => { window.__freeze = true; }); await sleep(600);   // measure what the frame shows: fonts in, nothing moving
        const g = await p.evaluate(() => {
          const a = document.getElementById('snapin-cta'), cue = a.querySelector('.cue'), img = a.querySelector('img'), svg = a.querySelector('svg.tail');
          const c = cue.getBoundingClientRect(), im = img.getBoundingClientRect(), cs = getComputedStyle(cue);
          return { c: [c.left, c.top, c.width, c.height], im: [im.left, im.top, im.width, im.height], bw: parseFloat(cs.borderBottomWidth), radius: parseFloat(cs.borderBottomLeftRadius),
            tail: svg ? { corner: svg.dataset.corner.split(',').map(Number), arc: svg.dataset.arc.split(',').map(Number), base: svg.dataset.base.split(';').map((q) => q.split(',').map(Number)), tip: svg.dataset.tip.split(',').map(Number), face: svg.dataset.face.split(',').map(Number) } : null,
            ink: cs.borderBottomColor, paper: cs.backgroundColor };
        });
        const [cl, ct, cw, chh] = g.c, clip = { x: Math.max(0, cl - 70), y: Math.max(0, ct - 30), width: Math.min(cw + 90, W - Math.max(0, cl - 70)), height: 110 };
        const png = await p.screenshot({ clip, timeout: 30000 });
        fs.writeFileSync(path.join(OUT, `cue-${W}-spot${n}.png`), png);
        const tag = `${W} spot ${n}`;
        if (!g.tail) { ok(false, `${tag}: the cue has a tail drawn from the bubble's edge (none: the old rotated square)`); continue; }
        const [cx, cy, R, bw] = g.tail.corner, [A0, A1] = g.tail.arc, [b0, b1] = g.tail.base, [tx, ty] = g.tail.tip, [fx, fy] = g.tail.face, H = g.c[3];
        const at = (deg, rad) => [cx + rad * Math.cos(deg * Math.PI / 180), cy + rad * Math.sin(deg * Math.PI / 180)];
        const onLine = (q) => Math.abs(Math.hypot(q[0] - cx, q[1] - cy) - (R - bw / 2)) < 0.6;
        ok(onLine(b0) && onLine(b1) && A0 >= 90 && A1 <= 180, `${tag}: the tail's base sits on the bubble's border, along its rounded bottom-left corner (${A0}°–${A1}°, radius ${R})`);
        // pixels (2x crop): the border is open (paper) mid-arc, ink just past each end of the opening, paper in the wedge's middle
        const o = (q) => [cl - clip.x + q[0], ct - clip.y + q[1]], mid = at((A0 + A1) / 2, R - bw / 2);
        const px = await p.evaluate(async ([src, pts]) => {
          const im = new Image(); im.src = src; await im.decode(); const cv = document.createElement('canvas'); cv.width = im.width; cv.height = im.height;
          const x = cv.getContext('2d'); x.drawImage(im, 0, 0); return pts.map(([u, v]) => Array.from(x.getImageData(Math.round(u * 2), Math.round(v * 2), 1, 1).data.slice(0, 3)));
        }, ['data:image/png;base64,' + png.toString('base64'), [o(mid), o(at(A0 - 14, R - bw / 2)), o(at(A1 + 9, R - bw / 2)), o([(b0[0] + b1[0] + tx) / 3, (b0[1] + b1[1] + ty) / 3])]]);
        const rgb = (q) => q.match(/\d+/g).slice(0, 3).map(Number), near = (q, t) => q.every((v, k) => Math.abs(v - t[k]) < 40);
        const INK = rgb(g.ink), PAPER = rgb(g.paper);
        ok(near(px[0], PAPER) && near(px[1], INK) && near(px[2], INK) && near(px[3], PAPER),
          `${tag}: the tail joins the border with no gap and no line across it (border mid-opening ${px[0]}, past each end ${px[1]} / ${px[2]}, wedge middle ${px[3]})`);
        const ang = (Math.atan2(fy - ty, fx - tx) - Math.atan2(ty - mid[1], tx - mid[0])) * 180 / Math.PI, err = Math.abs(((ang + 540) % 360) - 180);
        const inBubble = tx > 0 && tx < g.c[2] && ty > 0 && ty < H && Math.hypot(tx - cx, ty - cy) < R;
        const im = g.im, fxAbs = g.c[0] + tx, fyAbs = g.c[1] + ty;
        const inFace = fxAbs > im[0] + im[2] * 0.17 && fxAbs < im[0] + im[2] * 0.542 && fyAbs > im[1] + im[3] * 0.30 && fyAbs < im[1] + im[3] * 0.604;
        ok(err < 10 && !inBubble && !inFace, `${tag}: it points at Satrenchi's face (${err.toFixed(1)}° off the line to the face's edge, ${Math.hypot(fx - tx, fy - ty).toFixed(0)} px away; the tip is outside the bubble and the face)`);
      }
    }
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.message || e).slice(0, 300)); }
  await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  arena.child.kill(); web.child.kill();
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  console.log(`${pass} passed, ${fail} failed; frames in ${OUT}`);
  process.exit(fail ? 1 : 0);
})();
