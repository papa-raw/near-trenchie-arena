// Board 3's fight effects, placed and timed as final/SPEC.md says, with real three.js in node: the swing arc centred on the
// sim facing, the impact star on the struck side (never on the face), its size and life, the dust count, a beam to its sim
// end point after a 150 ms charge, the sweep turning 60 degrees over the sim's duration, the shockwave reaching 3 tiles, a
// shot never ahead of its tick, the KO stars only after the freeze, the drop flying from its KO, and the 150-shape cap with
// KOs first. Run: node near/web/arena-fight-geometry-case.mjs
import assert from 'node:assert/strict';
import { register } from 'node:module';
register('./arena-view-remainder-loader.mjs', import.meta.url);   // resolves 'three' to the vendored build
const ctx2d = new Proxy({ createRadialGradient: () => ({ addColorStop() {} }) }, { get: (o, k) => (k in o ? o[k] : () => {}) });
globalThis.document = { createElement: () => ({ width: 128, height: 128, getContext: () => ctx2d }) };
const THREE = await import('three');
const { Fight } = await import('./arena/fight.mjs');
let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const near = (a, b, e = 0.05) => Math.abs(a - b) <= e;
const T = 50;
function setup(records, actors = new Map()) {
  const f = new Fight(new THREE.Scene());
  for (const r of records) f.add(r);
  const ctx = { actors: { get: (id) => actors.get(id) }, objects: new Map(), budget: 150 };
  return { f, ctx, draw: (ms, extra = {}) => { f.draw(ms, { ...ctx, ...extra }); f.group.updateMatrixWorld(true); } };
}
const sprites = (f) => f.sprites.filter((s) => s.visible);
const meshes = (f) => [...f.meshes.values()].filter((m) => m.visible);

// the slam's floor band (SPEC 2a): centred on the aim at the sim's hit range (1.0-1.3 tiles, +-60 deg), flat at y 0.05, from
// the hit tick, gone by 220 ms; the head's trail around the swinger's hand when the actor has a slam this frame
for (const dir of [0, 90, 200, 315]) {
  const { f, draw } = setup([{ kind: 'arc', tick: 100, p: { x: 0, z: 0 }, dir, id: 'swinger' }]);
  draw(100 * T - 1); ok(meshes(f).length === 0, 'slam band: nothing before the hit tick (no slam this frame)');
  draw(100 * T + 60);
  const m = meshes(f)[0], mid = new THREE.Vector3(1.15, 0, 0).applyMatrix4(m.matrixWorld), L = Math.hypot(mid.x, mid.z);
  ok(near(mid.x / L, Math.cos(dir * Math.PI / 180)) && near(mid.z / L, Math.sin(dir * Math.PI / 180)), `slam band: centred on the aim ${dir} (got ${(mid.x / L).toFixed(2)}, ${(mid.z / L).toFixed(2)})`);
  ok(near(mid.y, 0.05, 0.001) && near(L, 1.15, 0.01) && m.geometry.parameters.outerRadius === 1.3 && near(m.geometry.parameters.thetaLength, 2 * Math.PI / 3, 1e-9), 'slam band: 1.0-1.3 tiles, +-60 deg, flat on the floor');
  draw(100 * T + 221); ok(meshes(f).length === 0, 'slam band: gone by 220 ms');
}
{
  const slam = { H: new THREE.Vector3(0, 1.73, 0), u: new THREE.Vector3(1, 0, 0), Lc: 1.4, phi: 0.5 };
  const actors = new Map([['swinger', { slam, h: { object3d: new THREE.Object3D() } }]]);
  const { f, draw } = setup([{ kind: 'arc', tick: 100, p: { x: 0, z: 0 }, dir: 0, id: 'swinger' }], actors);
  draw(100 * T - 40); const tr = meshes(f).find((m) => m.geometry.parameters.outerRadius === 1.32);
  ok(tr && tr.position.distanceTo(slam.H) < 1e-6 && near(tr.scale.x, 1.4 * 0.78, 1e-6), 'slam trail: around the hand, just inside the head path, before the hit');
  draw(100 * T + 121); ok(meshes(f).every((m) => m.geometry.parameters.outerRadius !== 1.32), 'slam trail: gone 120 ms after the hit');
}
{ // a slam's star lands on the crown: the target 0.12 tiles toward the swinger, 1.36 tiles up
  const { f, draw } = setup([{ kind: 'hit', tick: 150, s: { x: 1.3, z: 0 }, d: { x: 0, z: 0 }, heavy: false, move: 'swing' }]);
  draw(150 * T); const star = sprites(f).find((q) => q.position.y > 1);
  ok(star && near(star.position.x, 0.12) && near(star.position.y, 1.36) && near(star.position.z, 0), 'slam: its star sits on the crown');
}

// the impact star: 0.5 tiles toward the attacker, 0.1 under the chest, 50% -> 100% in 50 ms, gone by 150 ms; 2 or 4 puffs
for (const heavy of [false, true]) {
  const { f, draw } = setup([{ kind: 'hit', tick: 200, s: { x: 3, z: 0 }, d: { x: 0, z: 0 }, heavy }]);
  draw(200 * T - 1); ok(sprites(f).length === 0, 'hit: nothing before its tick');
  draw(200 * T);
  const star = sprites(f).find((s) => s.material.map === f.sprites[0].material.map && s.position.y > 0.5);
  ok(star && near(star.position.x, 0.5) && near(star.position.z, 0) && near(star.position.y, 0.6), 'hit: the star sits 0.5 tiles toward the attacker, below the face');
  ok(near(star.scale.x, (heavy ? 0.8 : 0.55) * 0.5), 'hit: the star starts at half size');
  draw(200 * T + 50); ok(near(sprites(f).find((s) => s.position.y > 0.5).scale.x, heavy ? 0.8 : 0.55), `hit: the star is ${heavy ? 0.8 : 0.55} tiles at 50 ms`);
  ok(sprites(f).filter((s) => s.position.y < 0.5).length === (heavy ? 4 : 2), `hit: ${heavy ? 4 : 2} dust puffs`);
  draw(200 * T + 151); ok(!sprites(f).some((s) => s.position.y > 0.5), 'hit: the star is gone after 150 ms');
}
{ // two hits at once on one body from two sides: two stars on two sides
  const { f, draw } = setup([{ kind: 'hit', tick: 300, s: { x: 3, z: 0 }, d: { x: 0, z: 0 }, heavy: false }, { kind: 'hit', tick: 300, s: { x: -3, z: 0 }, d: { x: 0, z: 0 }, heavy: false }]);
  draw(300 * T + 20); const xs = sprites(f).filter((s) => s.position.y > 0.5).map((s) => Math.sign(s.position.x)).sort();
  ok(xs.join() === '-1,1', 'hit: two hits from two sides show two stars on two sides');
}

// the beam: a 150 ms charge, then the cylinders to the sim's end point (range along its angle), faded 120 ms after its tick
{
  const { f, draw } = setup([{ kind: 'beam', tick: 400, owner: null, angle: 90, range: 6000, x: 0, y: 0, width: 1, end: 400 }]);
  draw(400 * T - 151); ok(sprites(f).length + meshes(f).length === 0, 'beam: nothing before its charge');
  draw(400 * T - 100); ok(sprites(f).length === 1 && meshes(f).length === 0, 'beam: the charge puff, no beam yet');
  draw(400 * T + 10);
  const outer = meshes(f).find((m) => m.geometry.parameters.openEnded);
  ok(outer && near(outer.position.z, 3, 0.2) && near(outer.position.x, 0, 0.05) && near(outer.scale.y, 6, 0.3), 'beam: from the weapon to 6 tiles along its sim angle');
  draw(400 * T + 50 + 121); ok(meshes(f).length === 0, 'beam: gone 120 ms after its end');
}
// the sweep turns its 60 degrees over its own duration
{
  const { f, draw } = setup([{ kind: 'sweep', tick: 500, owner: null, angle: 0, range: 4500, x: 0, y: 0, width: 1.3, end: 520 }]);
  const at = (ms) => { draw(ms); const m = meshes(f).find((q) => q.geometry.parameters.openEnded); return Math.atan2(m.position.z, m.position.x) * 180 / Math.PI; };
  ok(near(at(500 * T), 0, 1), 'sweep: starts on its sim angle');
  ok(near(at(510 * T), 30, 1), 'sweep: half way at half its duration');
  ok(near(at(520 * T - 1), 60, 1), 'sweep: 60 degrees across by its end');
}
// the shockwave: 3 tiles at 450 ms, 10 puffs on its edge, faded by 750 ms
{
  const { f, draw } = setup([{ kind: 'wave', tick: 600, p: { x: 0, z: 0 }, r: 3 }]);
  draw(600 * T + 450); const m = meshes(f)[0];
  ok(near(m.scale.x, 3, 0.01) && sprites(f).length === 10, 'wave: 3 tiles at 450 ms with 10 dust puffs');
  draw(600 * T + 751); ok(meshes(f).length === 0, 'wave: gone by 750 ms');
}
// a shot is never drawn ahead of its own tick (it exists in the next snapshot first)
{
  const { f, draw } = setup([{ kind: 'shot', key: 'object:1', tick: 700, from: { x: 0, y: 0.7, z: 0 }, to: { x: 5, y: 0.7, z: 0 }, start: { x: 0, z: 0 } }]);
  const objects = new Map([['object:1', { x: 0.2, z: 0 }]]);
  draw(700 * T - 10, { objects }); ok(meshes(f).length === 0, 'shot: not drawn before its tick');
  draw(700 * T + 10, { objects }); ok(meshes(f).length === 1, 'shot: drawn from its tick');
}
// the KO: no stars during the 200 ms freeze; the poof grows from +1300 ms after it
{
  const body = { position: new THREE.Vector3(1, 0, 1) }, actors = new Map([['victim', { h: { object3d: body } }]]);
  const { f, draw } = setup([{ kind: 'ko', tick: 800, d: { x: 1, z: 1 }, id: 'victim' }], actors);
  draw(800 * T + 199); ok(sprites(f).length === 0, 'ko: nothing during the freeze');
  draw(800 * T + 200 + 100); ok(sprites(f).length === 3, 'ko: 3 trailing stars in the launch');
  draw(800 * T + 200 + 1700); ok(sprites(f).length === 1 && sprites(f)[0].scale.x > 3, 'ko: the poof at +1700 ms');
}
// the drop flies from its KO's body, hidden in the body during the freeze, two bounces, lands where the sim put it
{
  const { f } = setup([{ kind: 'ko', tick: 900, d: { x: 0, z: 0 }, id: 'victim' }]);
  f.onDrops({ tick: 900, drops: [{ key: 'drop:9', x: 3500, y: 0 }, { key: 'drop:old', x: -9000, y: 0 }] });
  ok(f.dropPose('drop:9', 900 * T + 100).hidden, 'drop: hidden in the body during the freeze');
  const mid = f.dropPose('drop:9', 900 * T + 200 + 175);
  ok(mid.x > 0 && mid.x < 3.5 && mid.y > 0, 'drop: in flight from the body, in the air');
  const end = f.dropPose('drop:9', 900 * T + 200 + 700);
  ok(end.landed && near(end.x, 3.5) && near(end.y, 0), 'drop: lands where the sim put it');
  ok(f.dropPose('drop:old', 900 * T) === null, 'drop: one far from any KO has no flight');
  ok(f.dropPose('drop:ahead', 900 * T).hidden, 'drop: one in a snapshot ahead of its KO stays hidden');
  ok(new Fight(new THREE.Scene()).dropPose('drop:any', 0) === null, 'drop: a caller that fires no drops sees every drop where it lies');
}
// the cap: inside a 3-shape budget the KO is drawn first, dust last
{
  const body = { position: new THREE.Vector3() }, actors = new Map([['v', { h: { object3d: body } }]]);
  const { f, draw } = setup([{ kind: 'hit', tick: 1000, s: { x: 3, z: 0 }, d: { x: 0, z: 0 }, heavy: true }, { kind: 'ko', tick: 996, d: { x: 0, z: 0 }, id: 'v' }], actors);
  draw(1000 * T + 20, { budget: 3 });
  ok(f.live === 3 && sprites(f).length === 3 && sprites(f).every((s) => s.position.y >= 0.6), 'cap: 3 shapes, the KO stars first, no dust');
}
// the phone camera (SPEC section 8): who it follows, 2.8x reached over 300 ms, the subject at the view's centre; desktop unchanged
{
  const { pickSubject, CamFollow, PHONE_ZOOM } = await import('./arena/cam-follow.mjs');
  const recs = [{ kind: 'hit', tick: 100, sid: 'a', tid: 'b' }, { kind: 'hit', tick: 140, sid: 'c', tid: 'd' }, { kind: 'ko', tick: 120, id: 'e', by: 'f', uid: 7 }];
  ok(pickSubject(recs, 150 * T, 'me').ids.join() === 'me', 'camera: playing, it follows your own trenchie');
  ok(pickSubject(recs, 150 * T, null).ids.join() === 'e,f', 'camera: watching, the latest KO and its KO-er first');
  ok(pickSubject(recs.slice(0, 2), 150 * T, null).ids.join() === 'c,d', 'camera: else the latest exchange of hits');
  ok(pickSubject(recs.slice(0, 2), 150 * T + 5000, null) === null, 'camera: nothing for 4 s: the whole ring');
  const camera = new THREE.OrthographicCamera(-10, 10, 8, -12, 0.1, 400), view = { narrow: false };
  const stage = { camera, view, placeCamera() { camera.position.set(40, 50, 40); camera.up.set(0, 1, 0); camera.lookAt(0, 0, 0); camera.updateMatrixWorld(); } };
  const cam = new CamFollow(stage), where = (id) => ({ b: { x: 4, z: -3 }, a: { x: 2, z: -1 } }[id] || null);
  stage.placeCamera(); cam.apply(0, 110 * T, recs.slice(0, 1), null, where);
  ok(camera.zoom === 1, 'camera: desktop keeps the game framing (zoom 1)');
  view.narrow = true;
  stage.placeCamera(); cam.apply(1000, 110 * T, recs.slice(0, 1), null, where);
  ok(camera.zoom < 1.01, 'camera: phone, a new subject starts from where the view was');
  stage.placeCamera(); cam.apply(1150, 110 * T, recs.slice(0, 1), null, where);
  ok(camera.zoom > 1.5 && camera.zoom < PHONE_ZOOM, 'camera: half way through the 300 ms blend');
  stage.placeCamera(); cam.apply(1300, 110 * T, recs.slice(0, 1), null, where);
  const c = new THREE.Vector3(3, 0.6, -2).project(camera);   // the two fighters' centre, at chest height
  ok(near(camera.zoom, PHONE_ZOOM, 0.001), 'camera: 2.8x after 300 ms');
  ok(near(c.x, 0, 0.02) && near(c.y, 0, 0.02), `camera: the fight's centre sits at the frustum's centre, pads kept (ndc ${c.x.toFixed(3)}, ${c.y.toFixed(3)})`);
}
console.log('arena-fight-geometry-case: ' + checks + ' checks passed');
