// AOE telegraphs built out: c (red candles) is the default look, ?tele=a|b and ?tele=old stay for
// comparison, candles cast no shadow (budget lever 2), and the budget scene's &tele_n=N holds at least N live telegraphs.
//   node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-telegraph-c-case.mjs
import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { Effects, hitArea, teleLook } from './arena/fx.mjs';
import { stressTelegraphs, STRESS_TELE_TICKS } from './arena/budget-replay.mjs';

assert.equal(teleLook(''), 'c', 'no ?tele: red candles');
assert.equal(teleLook('?tele=a'), 'a');
assert.equal(teleLook('?tele=b'), 'b');
assert.equal(teleLook('?tele=c'), 'c');
assert.equal(teleLook('?tele=old'), 'old', 'the old flat shape stays reachable');
assert.equal(teleLook('?tele=constructor'), 'c', 'an unknown value keeps the default');

const fx = new Effects(new THREE.Scene(), {}, {}, {});
assert.equal(fx.teleLook, 'c', 'the arena draws c by default');
const N = 12;
let min = Infinity, max = 0, candles = 0;
const built = new Set();
for (let tick = 100; tick < 100 + 5 * STRESS_TELE_TICKS; tick++) {
  const snap = { objects: stressTelegraphs(N, tick), casts: [], drops: [] };
  fx.sync(snap, snap, 0, tick, tick * 50, new Map());
  min = Math.min(min, fx.tele.size); max = Math.max(max, fx.tele.size);
  for (const g of fx.tele.values()) {
    built.add(g);
    assert.equal(hitArea(g).style, 2, 'each live telegraph is c');
    assert.ok(g.userData.candles && g.userData.candles.castShadow === false, 'candles cast no shadow');
    candles = Math.max(candles, g.userData.candles.count);
  }
}
assert.ok(min >= N, `the stress scene holds at least ${N} live telegraphs (min ${min})`);
assert.equal(max, N, 'expired telegraphs leave the scene');
assert.ok(built.size <= 2 * N, `expired telegraphs are reused, not rebuilt (${built.size} built for ${5 * N} lives)`);
assert.ok([...fx.telePool.values()].every((l) => l.length <= 8), 'the pool keeps at most 8 spares a shape');
assert.ok([...fx.telePool.values()].flat().every((g) => !g.parent), 'pooled telegraphs are not drawn');
const shapes = new Set([...fx.tele.values()].map((g) => hitArea(g).shape));
assert.deepEqual([...shapes].sort(), ['circle', 'line'], 'stress covers circles (most candles) and beam lines');

const old = new Effects(new THREE.Scene(), {}, {}, {}, null, 'old');
const snap = { objects: stressTelegraphs(3, 100), casts: [], drops: [] };
old.sync(snap, snap, 0, 100, 0, new Map());
assert.ok([...old.tele.values()].every((m) => hitArea(m).style === 'old' && m.isMesh), '?tele=old draws the flat shape');
process.stdout.write(JSON.stringify({ ok: true, defaultLook: 'c', stress: N, liveMin: min, liveMax: max, maxCandlesPerTelegraph: candles, telegraphsBuilt: built.size }) + '\n');
