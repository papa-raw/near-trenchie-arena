// W9: the frame contract round-trips. Run: node near/web/arena-frame-case.mjs
import assert from 'node:assert/strict';
import { OrthographicCamera } from './vendor/three/three.module.min.js';
import { milliToWorld, worldToMilli, angleToRotY, rotYToAngle, lerpAngle, pickMilli, projectNdc, ARENA_RADIUS_MILLI } from './arena/frame.mjs';

let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };

// 1. milli-tiles <-> world units: x is east, sim y (south) is world z, height is world y
const w = milliToWorld(1500, -2250, 0.5);
ok(w.x === 1.5 && w.z === -2.25 && w.y === 0.5, 'sim (x, y) maps to world (x/1000, h, y/1000)');
for (const [x, y] of [[0, 0], [12000, 0], [-12000, 3], [7071, -7071], [1, 999], [-999, 1]]) {
  const back = worldToMilli(...[milliToWorld(x, y).x, milliToWorld(x, y).z]);
  ok(back.x === x && back.y === y, 'round trip ' + x + ',' + y);
}

// 2. facing: rotation.y sends the model front (+z) to (cos a, 0, sin a)
for (let a = 0; a < 360; a += 15) {
  const t = angleToRotY(a), fx = Math.sin(t), fz = Math.cos(t);
  ok(Math.abs(fx - Math.cos(a * Math.PI / 180)) < 1e-9 && Math.abs(fz - Math.sin(a * Math.PI / 180)) < 1e-9, 'front at ' + a + ' deg');
  ok(rotYToAngle(t) === a, 'inverse at ' + a);
}
ok(lerpAngle(350, 10, 0.5) === 360, 'facing turns the short way through 0');
ok(lerpAngle(10, 350, 0.5) === 0, 'and back');

// 3. picking: the iso camera, a screen point back to the milli-tile under it
const cam = new OrthographicCamera(-20, 20, 12, -12, 0.1, 200);
const az = Math.PI / 4, el = 35.264 * Math.PI / 180;
cam.position.set(Math.sin(az) * Math.cos(el) * 60, Math.sin(el) * 60, Math.cos(az) * Math.cos(el) * 60);
cam.up.set(0, 1, 0); cam.lookAt(0, 0, 0); cam.updateMatrixWorld(); cam.updateProjectionMatrix();
let worst = 0;
for (let x = -ARENA_RADIUS_MILLI; x <= ARENA_RADIUS_MILLI; x += 2000) for (let y = -ARENA_RADIUS_MILLI; y <= ARENA_RADIUS_MILLI; y += 2000) {
  const p = milliToWorld(x, y), n = projectNdc(p.x, 0, p.z, cam), got = pickMilli(n.x, n.y, cam);
  worst = Math.max(worst, Math.abs(got.x - x), Math.abs(got.y - y));
}
ok(worst <= 1, 'pick returns the milli-tile under the pixel to within 1 milli-tile (worst ' + worst + ')');
// the same answer as three's own projection
const pt = milliToWorld(3000, -4000);
const v = { x: pt.x, y: 0, z: pt.z }; const ref = new (cam.position.constructor)(v.x, v.y, v.z).project(cam);
const mine = projectNdc(pt.x, 0, pt.z, cam);
ok(Math.abs(ref.x - mine.x) < 1e-6 && Math.abs(ref.y - mine.y) < 1e-6, 'projectNdc agrees with three.js Vector3.project');
// a zoomed camera too
cam.zoom = 1.7; cam.updateProjectionMatrix();
const n2 = projectNdc(pt.x, 0, pt.z, cam), g2 = pickMilli(n2.x, n2.y, cam);
ok(Math.abs(g2.x - 3000) <= 1 && Math.abs(g2.y + 4000) <= 1, 'pick holds under camera.zoom');

console.log('arena-frame-case: ' + checks + ' checks passed');
