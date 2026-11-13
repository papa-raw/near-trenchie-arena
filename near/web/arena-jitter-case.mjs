// A character must hold its walk pose through hitstop and turn with weight instead of snapping its heading.
// Real rig and production actor path, render only; node near/web/arena-jitter-case.mjs.
import assert from 'node:assert/strict';
import { register } from 'node:module';
register('./arena-view-remainder-loader.mjs', import.meta.url);
await import('./arena-view-fix-env.mjs');
const THREE = await import('three');
const { LOOK3, ROSTER } = await import('./art/index.js');
const { Actors } = await import('./arena/actors.mjs');
const { angleToRotY } = await import('./arena/frame.mjs');
let checks = 0;
const ok = (v, m) => { assert.ok(v, m); checks++; };
const angle = (a, b) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b))) * 180 / Math.PI;
function setup(dir = 0) {
  const actors = new Actors(new THREE.Scene(), LOOK3, { roster: ROSTER }, {
    specs: {}, records: {}, clear() {}, equip() { return []; }, restoreGlow() {},
  });
  const f = { id: 'walker', x: 0, y: 0, dir, hp: 100, status: 0, shield: 0, items: {} };
  const draw = (now) => actors.update([{ ...f }], now / 50, now, 1000 / 60, new Map());
  draw(0);
  return { actors, f, draw, a: actors.get(f.id) };
}

{
  const { actors, f, draw, a } = setup();
  for (let i = 1; i < 12; i++) { f.x = i * 2.5 * 1000 / 60; draw(i * 1000 / 60); }
  const left = a.J.footL.position.clone(), right = a.J.footR.position.clone(), phase = a.phi;
  actors.onHit({ target: f.id, source: 'other', damage: 8, move: 'shot' }, 4, 200, { x: 0, z: 0 }, { x: 1, z: 0 });
  for (const now of [200, 216.6666667, 233.3333333]) {
    f.x = 2.5 * now; draw(now);
    ok(a.J.footL.position.distanceTo(left) < 1e-9 && a.J.footR.position.distanceTo(right) < 1e-9, 'hitstop holds the current feet, never the default rest pose');
    ok(a.phi === phase, 'step phase stays frozen during hitstop');
  }
  f.x = 625; draw(250);
  ok(a.phi > phase, 'distance stepping resumes after the hold');
  ok(a.J.footL.position.distanceTo(left) < .02, 'the feet resume without a reset pop');
}
{
  const { f, draw, a } = setup();
  const original = JSON.stringify(f);
  let heading = a.h.object3d.rotation.y;
  f.dir = 180;
  for (let i = 1; i <= 20; i++) {
    draw(i * 1000 / 60);
    const next = a.h.object3d.rotation.y;
    ok(angle(next, heading) <= 12.00001, 'body turns at most twelve degrees per 60 Hz frame');
    heading = next;
  }
  ok(angle(heading, angleToRotY(180)) < 1e-8, 'the turn reaches the requested heading');
  f.dir = 0;
  ok(JSON.stringify(f) === original, 'rendering never changes the input fighter');
}
{
  const { f, draw, a } = setup(359);
  const before = a.h.object3d.rotation.y;
  f.dir = 1; draw(1000 / 60);
  ok(angle(a.h.object3d.rotation.y, before) <= 2.00001, '359→1 follows the short arc');
  f.dir = 180; draw(1000);
  draw(0);
  ok(angle(a.h.object3d.rotation.y, angleToRotY(180)) < 1e-8, 'a render-time rewind resets heading history');
}
console.log(`character jitter: ${checks} checks passed`);
