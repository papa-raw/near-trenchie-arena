import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { LOOK3, ROSTER, ITEMS } from './art/index.js';
import { loadItems } from './items3d.js';
import { ActorInstances } from './arena/instances.mjs';
import { Actors } from './arena/actors.mjs';
import { Effects } from './arena/fx.mjs';
const items = await loadItems(ITEMS), scene = new THREE.Scene(), warnings = [], warn = console.warn;
console.warn = (...args) => warnings.push(args.join(' '));
try {
  const row = ROSTER[0], actors = new Actors(scene, LOOK3, { roster: ROSTER }, items);
  const f = { id: row.trenchieId, status: 0, x: 0, y: 0, hp: 100, dir: 0, items: { ...row.kit, weapon: 'future-item' } };
  const pos = actors.update([f], 1, 0, 16, new Map());
  const placeholder = actors.get(f.id).worn.find((g) => g.userData.itemRow === 'future-item');
  assert.equal(placeholder.userData.placeholder, true); assert.equal(placeholder.userData.label, 'Unknown item');
  items.restoreGlow(actors.get(f.id).worn);
  for (const group of actors.get(f.id).worn) group.traverse((m) => { if (m.isMesh && m.material.emissive) assert.ok(Number.isFinite(m.material.emissive.r), 'tier glow survives batching'); });
  const floor = items.floor('future-item'); assert.equal(floor.userData.item.userData.placeholder, true);
  actors.update([f], 2, 16, 16, new Map()); assert.equal(warnings.length, 1, 'unknown row logs once across floor and fighter');
  const fx = new Effects(scene, LOOK3, ITEMS, items); fx.setBounty([pos.get(f.id)], 0);
  const luminance = (hex) => { const c = new THREE.Color(hex); return .2126 * c.r + .7152 * c.g + .0722 * c.b; };
  const contrast = (a, b) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
  const contrasts = [];
  fx.bounty[0].traverse((o) => {
    if (o.isMesh) for (const sand of ['#F7F0DC', '#F6EAB3']) {
      const fg = o.material.color.clone().lerp(new THREE.Color(sand), 1 - o.material.opacity);
      const c = contrast(.2126 * fg.r + .7152 * fg.g + .0722 * fg.b, luminance(sand));
      if (o.name === 'bounty-rim') contrasts.push(c);
    }
  });
  const rimContrast = Math.min(...contrasts);
  assert.ok(rimContrast >= 3, 'holder rim contrast >= 3:1 on sand');
  const { guardedFrame } = await import('./arena/guard.mjs');
  const scheduled = [], faults = []; let frames = 0;
  const loop = guardedFrame(() => { if (++frames === 1) throw new Error('bad item'); }, (cb) => scheduled.push(cb), (e) => faults.push(e));
  loop(1); assert.equal(scheduled.length, 1); scheduled.shift()(2); assert.equal(frames, 2); assert.equal(faults.length, 1);
  const instances = new ActorInstances(scene);
  const f2 = { ...f, id: 'visitor-two', items: f.items, x: 3000 };
  actors.update([f, f2], 3, 32, 16, new Map()); instances.sync(actors);
  const sources = [];
  for (const actor of actors.map.values()) actor.h.object3d.traverseVisible((o) => { if (o.isMesh && o.layers.mask === 2) sources.push(o); });
  assert.ok(sources.length > 0, 'source meshes stay owned by actors while instances draw');
  const source = sources.find((o) => o.material.emissive && !o.material.map);
  const base = source.material.emissive.clone(); source.material.emissive.setRGB(1, 1, 1); instances.sync(actors);
  assert.ok([...instances.batches.values()].every(({ mesh }) => !Number.isNaN(mesh.material.color.r)), 'flash partition has finite colour');
  source.material.emissive.copy(base); instances.sync(actors);
  let disposed = 0; for (const { mesh } of instances.batches.values()) mesh.geometry.addEventListener('dispose', () => disposed++);
  actors.update([], 4, 48, 16, new Map()); instances.sync(actors);
  assert.equal(instances.batches.size, 0); assert.ok(disposed > 0, 'departed actors release instance resources');
  items.dispose(floor);
  process.stdout.write(JSON.stringify({ ok: true, unknownWarnings: warnings.length, frames, rimContrast: +rimContrast.toFixed(2) }) + '\n');
} finally { console.warn = warn; }
