import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { Effects, hitArea } from './arena/fx.mjs';
// each signature's approved visual shape, checked in the default look (c, red candles) and the old flat one
const expected = { beam_sweep: 'cone', blink_strike: 'circle', shockwave: 'ring', bubble: 'ring', chain_storm: 'ring', magnet: 'circle' };
for (const look of [null, 'old']) for (const [sig, type] of Object.entries(expected)) {
  const cast = { who: 'sprout', sig, resolveAt: 110, x: 2000, y: 3000 };
  const bound = { shape: sig === 'beam_sweep' ? 'cone' : 'circle', radiusMilli: 5400, arcMillidegrees: sig === 'beam_sweep' ? 48000 : 0, strikeRadiusMilli: 1200 };
  const fx = new Effects(new THREE.Scene(), {}, {}, {}, { geometry: () => bound }, look);
  const snap = { objects: [], casts: [cast], drops: [] }, positions = new Map([['sprout', { f: { x: 0, y: 0 } }]]);
  fx.sync(snap, snap, 0, 100, 0, positions);
  const mesh = [...fx.tele.values()][0];
  const area = hitArea(mesh);
  assert.equal(area.style, look ? 'old' : 2, sig + ' draws in the ' + (look || 'default c') + ' look');
  assert.equal(area.shape, type, sig + ' keeps its approved visual shape');
  assert.equal(area.r, sig === 'blink_strike' ? 1.2 : 5.4, sig + ' uses the correct bound dimension');
  if (type === 'cone') assert.ok(Math.abs(area.arc - 48 * Math.PI / 180) < 1e-9, sig + ' uses the bound arc');
  if (sig === 'blink_strike') { assert.equal(mesh.position.x, 2); assert.equal(mesh.position.z, 3); }
}
const rolled = new Effects(new THREE.Scene(), {}, {}, {}, { geometry: () => ({ radiusMilli: 2000, arcMillidegrees: 0 }) });
rolled.sync({ objects: [] }, { objects: [], casts: [{ who: 'sprout', sig: 'dodge_roll', resolveAt: 110 }], drops: [] }, 0, 100, 0, new Map());
assert.equal(rolled.tele.size, 0, 'dodge has no danger shape');
process.stdout.write(JSON.stringify({ ok: true, signatures: 6, looks: ['c', 'old'], blinkStrikeRadius: 1.2, shapesPreserved: true }) + '\n');
