// Board 3's no-clash check (the designer's final/measure/check.cjs), run against the live arena renderer: the seeded 16-fighter
// dev brawl streams to the real arena page; its requestAnimationFrame is taken over and its WebGL draw switched off, so the case
// steps the real renderer (actors, the slam, the fight effects, main.mjs's frame) every ~10 ms without the GPU, and on every
// step it looks for any held-stick vertex inside a body (radius 0.42, 0.05 to 1.4 tiles up) that the stick's owner is not
// hitting. Each clash is classed by what the owner is doing and how far apart the two bodies stand:
//   attack  an attack or a slam (SPEC 2, 2a): must be none (the sideways swing and the windup backswings are gone)
//   shove   the owner shoved after a hit       } SPEC 2a's residuals, at 1.25 tiles or more apart: tracked here so they are
//   ko      the owner in its KO launch         } not forgotten, each held to its measured depth (0.15, 0.33, 0.05 tiles, plus a
//   idle    two shouldered sticks             } little for the live crowd's own steps)
// Bodies the sim itself puts closer than 0.84 tiles (two body radii) are counted, not judged: no stick choice keeps them apart.
// On every slam's hit frame it also measures how far the stick's head is from the target's crown (SPEC: 0.03 to 0.11 tiles).
//
// Run:  NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/web/arena-fight-clash-case.cjs [seconds]
'use strict';
const net = require('net');
const path = require('path');
const { chromium } = require('playwright');
const HOSTS = require('./snapin/qa/hosts.cjs');

const ROOT = path.resolve(__dirname, '..', '..');
const SECONDS = +(process.argv[2] || 60);
const R = 0.42, TOP = 1.4, APART = 1.25, TOUCH = 0.84;
const RESIDUAL = { shove: 0.15 + 0.05, ko: 0.33 + 0.05, idle: 0.05 + 0.05 };   // SPEC 2a's measured depths, plus 0.05 tile
let failures = 0, checks = 0;
const ok = (cond, msg) => { checks++; if (!cond) { failures++; console.log('FAIL ' + msg); } };
const freePort = () => new Promise((res) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
const up = (port) => new Promise((res) => { const t0 = Date.now(); const tryit = () => { const c = net.connect(port, '127.0.0.1', () => { c.end(); res(true); }); c.on('error', () => (Date.now() - t0 > 15000 ? res(false) : setTimeout(tryit, 200))); }; tryit(); });

async function main() {
  const [wsPort, webPort] = [await freePort(), await freePort()];
  const quiet = { stdio: ['pipe', 'ignore', 'ignore'] };
  HOSTS.host(['-B', path.join(ROOT, 'near/arena/dev_brawl.py'), '--port', String(wsPort), '--seed', '7', '--crowd', '16'], quiet);
  HOSTS.host(['-m', 'http.server', String(webPort), '--bind', '127.0.0.1', '--directory', path.join(ROOT, 'near')], quiet);
  ok(await up(wsPort) && await up(webPort), 'the dev brawl and the page server start');
  const lane = !!process.env.HTTPS_PROXY;
  const browser = await chromium.launch(lane ? { args: ['--single-process', '--no-zygote', '--use-gl=angle', '--use-angle=swiftshader-webgl', '--enable-unsafe-swiftshader'], proxy: { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' } } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errs = []; page.on('pageerror', (e) => errs.push(String(e).slice(0, 200)));
  // take over the frame clock before the page starts: frames run only when the case steps them
  await page.addInitScript(() => {
    const q = []; window.requestAnimationFrame = (cb) => { q.push(cb); return q.length; };
    window.__step = (now) => { const run = q.splice(0); for (const cb of run) cb(now); };
  });
  await page.goto(`http://127.0.0.1:${webPort}/web/arena.html?ws=ws://127.0.0.1:${wsPort}`);
  await page.waitForFunction(() => window.ARENA && window.ARENA.actors, null, { timeout: 60000, polling: 500 });   // timed: the case owns requestAnimationFrame
  await page.evaluate(() => {
    const A = window.ARENA; A.stage.renderer.render = () => {};   // geometry only: no GPU draw
    const T = A.THREE, v = new T.Vector3(), R = 0.42, TOP = 1.4;
    window.__res = { steps: 0, clashes: {}, strikes: [], bodies: 0 };
    window.__check = () => {
      const now = performance.now(); window.__step(now);
      const s = A.buffer.sample(now); if (!s) return;
      const ms = s.tick * 50, out = window.__res; out.steps++;
      const actors = [...A.actors.map.values()]; out.bodies = Math.max(out.bodies, actors.length);
      // whom each owner is hitting now: its hits from 200 ms before to 500 ms after, and the one its slam is coming down on
      const hitting = new Map();
      for (const r of A.fx.fight.records) if (r.kind === 'hit' && r.sid && ms >= r.tick * 50 - 200 && ms < r.tick * 50 + 500) { if (!hitting.has(r.sid)) hitting.set(r.sid, new Set()); hitting.get(r.sid).add(r.tid); }
      for (const a of actors) for (const m of a.anims) if (m.kind === 'attack' && m.target) { if (!hitting.has(a.id)) hitting.set(a.id, new Set()); hitting.get(a.id).add(m.target); }
      for (const a of actors) {
        const o = a.h.object3d, M = a.J.mountWeapon; if (!o.visible || !M.children.length) continue;
        const atk = a.anims.find((m) => m.kind === 'attack'), what = atk ? atk.weapon + (a.slam ? ' slam age ' + Math.round(a.slam.age) : ' u ' + Math.round(ms - atk.tick * 50)) : '';
        const busy = atk ? 'attack' : a.anims.some((m) => m.kind === 'hit') ? 'shove' : (a.koAt !== null && ms - a.koAt < 1700) ? 'ko' : 'idle';
        const pts = []; M.updateWorldMatrix(true, true);
        M.traverse((m) => { if (m.isMesh) { const pa = m.geometry.attributes.position; for (let i = 0; i < pa.count; i += 2) pts.push(v.fromBufferAttribute(pa, i).applyMatrix4(m.matrixWorld).clone()); } });
        const hs = hitting.get(a.id) || new Set();
        for (const g of actors) {
          if (g === a || hs.has(g.id) || !g.h.object3d.visible) continue;
          const gp = g.h.object3d.position; let deep = 0;
          for (const q of pts) { const d = Math.hypot(q.x - gp.x, q.z - gp.z); if (d < R && q.y > gp.y + 0.05 && q.y < gp.y + TOP) deep = Math.max(deep, R - d); }
          if (!deep) continue;
          const apart = Math.hypot(o.position.x - gp.x, o.position.z - gp.z), key = busy + (apart < 0.84 ? ':touching' : apart < 1.25 ? ':close' : '');
          const c = out.clashes[key] || (out.clashes[key] = { n: 0, deep: 0, apart: 99, eg: '' });
          c.n++; if (deep > c.deep) { c.deep = +deep.toFixed(3); c.eg = a.id + '>' + g.id + ' @' + Math.round(ms) + ' apart ' + apart.toFixed(2) + (what ? ' (' + what + ')' : ''); } c.apart = Math.min(c.apart, +apart.toFixed(2));
        }
        // the slam's head on the crown, on the hit frame (age 150, held through hitstop)
        const slam = a.anims.find((m) => m.kind === 'attack' && m.crown);
        if (a.slam && slam && a.slam.age >= 149 && a.slam.age <= 151) { const P = new T.Vector3(slam.crown.x, slam.crown.y, slam.crown.z); let best = 1e9; for (const q of pts) best = Math.min(best, q.distanceTo(P)); out.strikes.push(+best.toFixed(3)); }
      }
    };
  });
  const end = Date.now() + SECONDS * 1000;
  while (Date.now() < end) { await page.evaluate(() => window.__check()); await page.waitForTimeout(8); }
  const res = await page.evaluate(() => window.__res);
  await browser.close();
  const left = await HOSTS.finish();

  ok(errs.length === 0, `no page errors (${errs.join('; ')})`);
  ok(left.length === 0, `no host this case started survives it (${left.length} left)`);
  ok(res.bodies >= 16 && res.steps > 500, `the real renderer stepped ${res.steps} times over a ${res.bodies}-fighter crowd`);
  const at = (cls) => res.clashes[cls] || { n: 0, deep: 0, eg: '' };
  for (const cls of ['attack']) ok(at(cls).n === 0, `no attack or slam puts a stick into a body it is not hitting (${cls}: ${at(cls).n} frames, deepest ${at(cls).deep} ${at(cls).eg})`);
  for (const cls of ['shove', 'ko', 'idle']) ok(at(cls).deep <= RESIDUAL[cls], `${cls} residual at ${APART}+ tiles apart within SPEC 2a's ${RESIDUAL[cls].toFixed(2)} tiles (deepest ${at(cls).deep} over ${at(cls).n} frames ${at(cls).eg})`);
  ok(res.strikes.length > 0 && res.strikes.every((d) => d <= 0.15), `each slam's head lands on the crown (${res.strikes.length} hits, farthest ${res.strikes.length ? Math.max(...res.strikes) : '-'} tiles; SPEC 0.03-0.11)`);
  console.log('clashes by class (frames, deepest tiles, closest pair):', JSON.stringify(Object.fromEntries(Object.entries(res.clashes).map(([k, c]) => [k, [c.n, c.deep, c.apart]]))));
  console.log(`arena-fight-clash-case: ${checks - failures}/${checks} checks passed (${res.steps} steps, ${TOUCH}-tile touching pairs counted, not judged)`);
  process.exit(failures ? 1 : 0);
}
main().catch((e) => { console.log('FAIL crashed: ' + (e && e.stack || e)); process.exit(1); });
