import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { SnapshotBuffer } from './arena/buffer.mjs';
import * as THREE from 'three';
import { LOOK3, ROSTER, ITEMS } from './art/index.js';
import { loadItems } from './items3d.js';
import { ActorInstances } from './arena/instances.mjs';
import { CastDetails } from './arena/quirks.mjs';
import { Actors } from './arena/actors.mjs';
import { Effects } from './arena/fx.mjs';
import { buildIsland } from './arena/scene.mjs';
import { BudgetReplay, budgetEffects } from './arena/budget-replay.mjs';
const scene = new THREE.Scene(); LOOK3.setTreatment('cel'); scene.add(buildIsland());
const details = new CastDetails();
const items = await loadItems(ITEMS), actors = new Actors(scene, LOOK3, { roster: ROSTER }, items, process.argv.includes('--reduced') ? { arenaQuality: true } : undefined), fx = new Effects(scene, LOOK3, ITEMS, items, details);
assert.equal(actors.arenaQuality, process.argv.includes('--reduced'), 'full detail is the default; reduced is explicit');
const fighters = ROSTER.map((r, i) => ({ id: r.trenchieId, x: Math.cos(i * 2.4) * 6500, y: Math.sin(i * 2.4) * 6500, dir: 0, status: 0, hp: 100, items: r.kit }));
for (const [i, id] of ['sand-sprout', 'tidal-turnip'].entries()) fighters.push({ id, x: i * 2000, y: 0, dir: 0, status: 0, hp: 100, items: { head: 'st-cap', body: 'st-tee', trinket: 'st-roll', weapon: i ? 'c-lob' : 'c-zap' } });
const positions = actors.update(fighters, 1, 0, 16, new Map());
fx.setCrown({ x: 0, z: 0 }, 1.55, 0);
const empty = { objects: [], casts: [], drops: [] }; fx.sync(empty, empty, 0, 1, 0, positions); budgetEffects(scene);
// Count colour and one shadow pass, without frustum culling: conservative scene-graph proxy, never GPU timing.
function count() {
  scene.updateMatrixWorld(true); let calls = 0, triangles = 0, meshes = 0;
  scene.traverseVisible((o) => {
    if (!o.isMesh || !(o.layers.mask & 1)) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material], g = o.geometry, instances = o.isInstancedMesh ? o.count : 1;
    for (const group of Array.isArray(o.material) ? g.groups : [{ start: 0, count: g.index ? g.index.count : g.attributes.position.count, materialIndex: 0 }]) {
      const m = mats[group.materialIndex]; if (!m?.visible) continue;
      const passes = 1 + Number(m.transparent && m.side === THREE.DoubleSide && !m.forceSinglePass) + Number(o.castShadow);
      calls += passes; triangles += group.count / 3 * instances * passes;
    }
    meshes++;
  });
  return { calls, triangles: Math.round(triangles), meshes, fighters: fighters.length, effects: 150, tessellation: process.argv.includes('--reduced') ? 'reduced' : 'full' };
}
const instances = new ActorInstances(scene); instances.sync(actors);
assert.ok(instances.batches.size > 0, 'repeated actor primitives are instanced');
const matrix = new THREE.Matrix4();
for (const { mesh } of instances.batches.values()) for (let i = 0; i < mesh.count; i++) {
  mesh.getMatrixAt(i, matrix); assert.ok(matrix.determinant() > 0, 'instances retain positive transforms');
}

let result = count();
if (process.argv.includes('--record')) {
  const record = JSON.parse(await readFile(process.argv[process.argv.indexOf('--record') + 1], 'utf8'));
  const buffer = new SnapshotBuffer(), replay = new BudgetReplay(record, buffer, { onMetadata: (message) => details.apply(message) }), stress = scene.getObjectByName('budget-effects');
  const samples = [];
  // Every recorded tick is decoded; sample every second plus each distinct floor/cast state.
  let lastState = '';
  for (let now = 0; now <= 65000; now += 50) {
    replay.pump(now); const sample = buffer.sample(now); if (!sample) continue;
    const signature = JSON.stringify([sample.b.drops, sample.b.casts, sample.b.objects]);
    if (now % 1000 && signature === lastState) continue; lastState = signature;
    const { a, b, k, tick } = sample;
    const pos = actors.update(b.fighters, tick, now, 50, new Map());
    fx.sync(a, b, k, tick, now, pos); fx.setBounty(b.fighters.filter((f) => Object.values(f.items).some((id) => ITEMS[id]?.tier === 'legendary' && ITEMS[id].origin !== 'house:' + f.id)).map((f) => pos.get(f.id)), now);
    stress.children.forEach((m, i) => { m.visible = i < Math.max(0, 150 - fx.liveShapes); });
    instances.sync(actors); const cost = count(); samples.push(cost);
  }
  result = { ...result, calls: Math.max(...samples.map((s) => s.calls)), triangles: Math.max(...samples.map((s) => s.triangles)), samples: samples.length, ticks: record.frames.length };
}
process.stdout.write(JSON.stringify(result) + '\n');
if (!process.argv.includes('--measure')) { assert.ok(result.calls <= 550, 'draw-call proxy <= 550'); if (process.argv.includes('--reduced')) assert.ok(result.triangles <= 600000, 'reduced-mode triangle proxy <= 600000'); }
