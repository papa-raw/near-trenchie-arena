// Real rig: a new life fades at its old position without scaling, then appears at its ring position without a drop.
import assert from 'node:assert/strict';
import { register } from 'node:module';
register('./arena-view-remainder-loader.mjs', import.meta.url);
await import('./arena-view-fix-env.mjs');
const THREE = await import('three');
const { LOOK3, ROSTER } = await import('./art/index.js');
const { Actors } = await import('./arena/actors.mjs');
const { pose, TOTAL_MS, Prejump } = await import('./arena/prejump.mjs');
const actors = new Actors(new THREE.Scene(), LOOK3, { roster: ROSTER }, { specs: {}, records: {}, clear() {}, equip() { return []; }, restoreGlow() {} });
const fighter = { id: 'coral', x: 1000, y: 2000, dir: 0, hp: 100, status: 1, shield: 0, items: {} };
const other = { ...fighter, id: 'pebble', status: 0, x: -3000 };
const bench = new Map([['coral', { x: 6000, y: -4000, dir: 45 }]]);
actors.update([fighter, other], 20, 1000, 16, bench);
const a = actors.get('coral'), b = actors.get('pebble');
const position = a.h.object3d.position.clone(), scale = a.h.object3d.scale.clone(), baseScale = a.J.base.scale.clone();
function materials(actor) {
  const out = new Set(); actor.h.object3d.traverse((node) => { for (const m of [].concat(node.material || [])) out.add(m); }); return [...out];
}
const original = new Map(materials(a).map((m) => [m, { opacity: m.opacity, transparent: m.transparent, depthWrite: m.depthWrite }]));
const untouched = new Map(materials(b).map((m) => [m, m.opacity]));
actors.onRespawn({ fighter: 'coral', life_id: 2 }, 22, 1100, 300);
for (const elapsed of [0, 75, 150, 299, 300]) {
  actors.update([{ ...fighter, status: 0 }, other], (1100 + elapsed) / 50, 1100 + elapsed, 16, bench);
  assert.ok(a.h.object3d.position.distanceTo(position) < 1e-9, 'the fading fighter stays where it was standing');
  assert.ok(a.h.object3d.scale.distanceTo(scale) < 1e-9 && a.J.base.scale.distanceTo(baseScale) < 1e-9, 'no body or joint scale change during pre-jump');
  for (const [m, before] of original) assert.ok(Math.abs(m.opacity - before.opacity * (1 - elapsed / 300)) < 1e-9, 'every material follows the plain opacity fade');
  for (const [m, opacity] of untouched) assert.equal(m.opacity, opacity, 'another fighter never fades');
}
actors.update([{ ...fighter, status: 0 }, other], 29, 1401, 16, bench);
assert.equal(a.h.object3d.position.x, 1); assert.equal(a.h.object3d.position.z, 2);
assert.equal(a.J.base.position.y, 0, 'appears in ring without a vertical drop');
for (const [m, before] of original) {
  assert.equal(m.opacity, before.opacity); assert.equal(m.transparent, before.transparent); assert.equal(m.depthWrite, before.depthWrite);
}
for (const t of [0, 75, 150, 299, 300]) {
  const p = pose(t, { x: 200, y: 400 }, { x: 500, y: 200 });
  assert.deepEqual([p.x, p.y, p.scale], [200, 400, 1]); assert.ok(Math.abs(p.opacity - (1 - t / 300)) < 1e-9);
}
assert.equal(TOTAL_MS, 300);
class Element {
  constructor() { this.style = {}; this.dataset = {}; this.children = []; this.offsetWidth = 100; this.offsetHeight = 30; }
  append(...els) { this.children.push(...els); }
  appendChild(el) { this.children.push(el); }
  setAttribute() {}
  remove() { this.removed = true; }
}
const doc = { createElement: () => new Element(), createTextNode: () => new Element() }, root = new Element();
const pre = new Prejump(doc, root); pre.start('coral', 'Coral Clerk', 2, 1000);
pre.frame(1000, () => ({ x: 200, y: 400 }), () => ({ x: 500, y: 200 })); const card = root.children[0], transform = card.style.transform;
assert.doesNotMatch(transform, /scale/);
pre.frame(1150, () => ({ x: 800, y: 600 }), () => ({ x: 500, y: 200 }));
assert.equal(card.style.transform, transform, 'card stays in place'); assert.equal(Number(card.style.opacity), 0.5);
pre.frame(1300, () => ({ x: 0, y: 0 })); assert.ok(card.removed); assert.equal(pre.on.size, 0);
process.stdout.write('arena-prejump-fade-case: stationary 300ms body/card fade, constant scale, opacity0, material restore and ring arrival OK\n');
