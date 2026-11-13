// Slow approaches must step, including the 0.15–0.25 tile/s motion captured in sliding-diag.
// Real body rig + production actor updates; no GPU, model, server or rules changes.
// Run: node near/web/arena-slow-walk-case.mjs
import assert from 'node:assert/strict';
import { register } from 'node:module';
register('./arena-view-remainder-loader.mjs', import.meta.url);
await import('./arena-view-fix-env.mjs');
const THREE = await import('three');
const { LOOK3, ROSTER } = await import('./art/index.js');
const { Actors } = await import('./arena/actors.mjs');
let checks = 0;
const ok = (value, message) => { assert.ok(value, message); checks++; };

function walker() {
  const actors = new Actors(new THREE.Scene(), LOOK3, { roster: ROSTER }, {
    specs: {}, records: {}, clear() {}, equip() { return []; }, restoreGlow() {},
  });
  const f = { id: 'walker', x: 0, y: 0, dir: 0, hp: 100, status: 0, shield: 0, items: {} };
  actors.update([f], 0, 0, 1000 / 60, new Map());
  return { actors, f, a: actors.get(f.id) };
}
function feet(a) {
  return [a.J.footL.position.distanceTo(a.def.footL), a.J.footR.position.distanceTo(a.def.footR)];
}
function walk(speed, fps, seconds = 6) {
  const { actors, f, a } = walker();
  let peak = 0, lifted = 0;
  for (let i = 1; i <= fps * seconds; i++) {
    const now = i * 1000 / fps;
    f.x = speed * now; // milli-tiles: tiles/second × milliseconds
    actors.update([f], now / 50, now, 1000 / fps, new Map());
    peak = Math.max(peak, ...feet(a));
    lifted = Math.max(lifted, a.J.footL.position.y - a.def.footL.y, a.J.footR.position.y - a.def.footR.y);
  }
  return { peak, lifted, phase: a.phi, a };
}

for (const fps of [30, 60]) {
  for (const speed of [0.02, 0.15, 0.25, 0.4, 3]) {
    const r = walk(speed, fps);
    ok(r.peak > 0.015, `${speed} tiles/s at ${fps} Hz: a visible foot step (got ${r.peak})`);
    ok(r.lifted > 0.008, `${speed} tiles/s at ${fps} Hz: a foot lifts`);
    ok(Math.abs(r.phase - speed * 6) < 1e-8, `${speed} tiles/s: step phase follows distance`);
  }
}
const idle = walk(0, 60);
ok(idle.peak === 0 && idle.phase === 0, 'stationary fighters do not walk');
const stopped = walker();
stopped.actors.update([{ ...stopped.f, x: 10 }], 1, 50, 50, new Map());
stopped.actors.update([{ ...stopped.f, x: 10 }], 2, 100, 50, new Map());
ok(feet(stopped.a).every(v => v === 0), 'feet return to rest as soon as translation stops');
const frozen = walker();
frozen.a.holds.push({ from: 0, until: 100, vib: 0, flash: 0 });
frozen.actors.update([{ ...frozen.f, x: 10 }], 1, 50, 50, new Map());
ok(feet(frozen.a).every(v => v === 0) && frozen.a.phi === 0, 'hitstop keeps the walk frozen');
const jump = walker();
jump.actors.update([{ ...jump.f, x: 5000 }], 1, 50, 50, new Map());
ok(jump.a.phi === 0, 'a teleport does not advance the step phase');
const bench = walker();
bench.actors.update([{ ...bench.f, status: 1 }], 1, 50, 50, new Map([[bench.f.id, { x: 4000, y: 0, dir: 0 }]]));
ok(feet(bench.a).every(v => v === 0), 'a bench relocation does not walk');
console.log(`slow walk: ${checks} checks passed`);
