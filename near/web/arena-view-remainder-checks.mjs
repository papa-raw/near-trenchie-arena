import * as THREE from 'three';
import { loadItems } from './items3d.js';
import { LOOK3, ROSTER, ITEMS } from './art/index.js';
import { Actors } from './arena/actors.mjs';
import { Effects } from './arena/fx.mjs';
import { Budget, FrameGate } from './arena/budget.mjs';
import { styleWord, hasBounty } from './arena/style.mjs';
import { decode, encode } from './arena/codec.mjs';
import { BudgetReplay, budgetEffects } from './arena/budget-replay.mjs';
export async function check({ render: draw = true } = {}) {
  let checks = 0;
  const ok = (v, why) => { if (!v) throw new Error(why); checks++; };
  LOOK3.setTreatment('cel');
  const items = await loadItems(ITEMS), scene = new THREE.Scene();
  const snap = decode(await (await fetch('./arena/fixtures/tick-recorded.json')).json());
  snap.fighters[0].items.trinket = 'leg-stack-sats'; // controlled theft fixture: Avichad wears Satrenchi's legendary
  const actors = new Actors(scene, LOOK3, { roster: ROSTER }, items);
  const pos = actors.update(snap.fighters, snap.tick, 0, 16, new Map()); let worn = 0;
  for (const [id, a] of actors.map) {
    const groups = []; a.h.object3d.traverse((o) => { if (o.userData.itemRow) groups.push(o); });
    ok(groups.length === 4, id + ' has four item children');
    ok(groups.every((g) => Object.values(pos.get(id).f.items).includes(g.userData.itemRow)), 'equipped rows match'); worn += groups.length;
  }
  const a = actors.get(snap.fighters[0].id), old = a.worn.slice(), f = snap.fighters[0];
  let freed = 0; old.forEach((g) => g.traverse((m) => { if (m.isMesh) m.geometry.addEventListener('dispose', () => freed++); }));
  actors.setItems(a, { ...f, items: { ...f.items, weapon: 'r-lob' }, itemRows: f.itemRows.map((v, i) => i === 3 ? -1 : v) });
  ok(old.every((g) => !g.parent || !g.parent.parent), 'replacement detaches old item groups'); ok(a.worn.length === 4, 'replacement does not accumulate'); ok(freed > 0, 'replacement frees geometry');
  const fx = new Effects(scene, LOOK3, ITEMS, items); fx.sync(snap, snap, 0, snap.tick, 0, pos);
  ok(fx.floor.size === snap.drops.length, 'floor drops drawn');
  ok([...fx.floor.values()].every((g) => g.position.y === 0), 'floor tier glow stays at ground: ' + [...fx.floor.values()].map((g) => g.position.y).join(','));
  ok([...fx.floor.values()].every((g) => g.userData.glow && g.userData.itemRow), 'approved floor glow');
  const holder = snap.fighters.find((q) => hasBounty(q, ITEMS)); ok(!!holder, 'stolen legendary fixture');
  fx.setBounty([pos.get(holder.id)], 0); ok(fx.bounty[0].visible && fx.bounty[0].position.y > 0, 'gold holder ring');
  fx.setBounty([], 0); ok(!fx.bounty[0].visible, 'ring clears');
  ok(!hasBounty({ ...holder, status: 1 }, ITEMS), 'no bench bounty');
  ok(!hasBounty({ ...holder, id: 'satrenchi', items: { trinket: 'leg-stack-sats' } }, ITEMS), 'own legendary has no bounty');
  let floorFreed = 0; [...fx.floor.values()].forEach((g) => g.traverse((m) => { if (m.isMesh) m.geometry.addEventListener('dispose', () => floorFreed++); }));
  fx.sync(snap, { ...snap, drops: [] }, 0, snap.tick, 0, pos);
  ok(fx.floor.size === 0 && floorFreed > 0, 'removed loot frees meshes');
  fx.sync(snap, snap, 0, snap.tick, 0, pos);
  const primitives = { sphere: { r: .2 }, hemisphere: { r: .2 }, cylinder: { r: .2, h: .3 }, cone: { r: .2, h: .3 }, box: { w: .2, h: .3, d: .2 }, torus: { r: .2, tube: .03 }, tube: { points: [[0,0,0],[0,.3,0]], width: .05 }, plate: { w: .2, h: .3, t: .03 } };
  for (const [type, size] of Object.entries(primitives)) {
    const g = items.buildSpec({ id: 'case-' + type, slot: 'weapon', tier: 'rare', nodes: [{ type: 'group', children: [{ type, color: 'p10', ...size }] }] });
    const box = new THREE.Box3().setFromObject(g); ok(!box.isEmpty() && Number.isFinite(box.max.x), 'draws ' + type);
    g.traverse((m) => { if (m.isMesh) ok(m.material.isMeshToonMaterial && m.material.gradientMap && m.material.emissive.getHexString() === '6fa3d6', 'rare toon tier'); });
    items.dispose(g);
  }
  for (const row of Object.keys(ITEMS)) { const g = items.build(row); ok(g.userData.itemRow === row, 'catalog ' + row); items.dispose(g); }
  const previousWarn = console.warn; let unknown;
  try { console.warn = () => {}; unknown = items.build('no-such-row'); } finally { console.warn = previousWarn; }
  ok(unknown.userData.placeholder && unknown.userData.label === 'Unknown item', 'unknown item is labelled'); items.dispose(unknown);
  ok(styleWord('guardian') === 'Guardian' && styleWord('unknown') === '', 'known styles only');
  ok(['brawler','hunter','looter','survivor'].every((s) => styleWord(s) === s[0].toUpperCase() + s.slice(1)), 'style words');
  const gate = new FrameGate(30), times = [];
  for (let t = 0; t < 1000; t += 1000 / 60) if (gate.ready(t)) times.push(t);
  ok(times.length >= 29 && times.length <= 31, '30 fps cap');
  const renderer = { getPixelRatio: () => 2, info: { render: { calls: 7, triangles: 50 }, memory: { geometries: 4, textures: 1 } } };
  const b = new Budget(1, 1000 / 30, { throttled: true });
  for (let i = 0; i <= 31; i++) b.sample(20, 1 + i * 1000 / 30, renderer, {});
  ok(b.result.line1_p95RenderOver12ms === null && !b.result.line2_fail && !b.result.line3_fail, 'throttle lines');
  ok(b.result.line4 === 'pending human review', 'human line pending');
  const received = [], record = { frames: [JSON.parse(encode(snap))], loadouts: Object.fromEntries(snap.fighters.map((f) => [f.id, f.items])) };
  new BudgetReplay(record, { push: (s) => received.push(s) }, { crowd: 3 }).pump(0);
  ok(received.length === 1 && received[0].fighters.every((f) => f.status === 0 && Object.keys(f.items).length === 4), 'recording uses full visible kits');
  const cluster = received[0].fighters.slice(0, 10);
  ok(cluster.every((f) => Math.hypot(f.x, f.y) <= 1101), 'ten bodies in one three-tile cluster');
  const stress = budgetEffects(scene); ok(stress.children.length === 150 && stress.children.every((m) => !m.castShadow), 'full effect stress without effect shadows');
  scene.remove(stress); items.dispose(stress);
  const failed = new Budget(1, 16.667);
  for (let i = 0; i <= 20; i++) failed.sample(13, i * 60, renderer, {});
  ok(failed.result.line1_p95RenderOver12ms && failed.result.line2_fail && failed.result.line3_fail, 'all numeric fail lines catch a slow run from t=0');
  if (!draw) return { ok: true, checks, worn, floor: fx.floor.size, holder: holder.id, browser: 'not run; geometry only' };
  const render = new THREE.WebGLRenderer({ canvas: document.getElementById('case'), antialias: true, preserveDrawingBuffer: true });
  render.setPixelRatio(2); render.setSize(1440, 720); render.shadowMap.enabled = true;
  const lights = LOOK3.setupScene(scene, render, { extent: 20 }); lights.update(new THREE.Vector3());
  const camera = new THREE.OrthographicCamera(-18, 18, 9, -9, .1, 200);
  camera.position.set(24,24,24); camera.lookAt(0,0,0); camera.updateMatrixWorld();
  fx.setBounty([pos.get(holder.id)], 0); render.render(scene, camera);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.MeshBasicMaterial({ color: '#F7F0DC' }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -.01; scene.add(ground); render.render(scene, camera);
  const full = document.createElement('canvas'); full.width = 2880; full.height = 1440; full.style.cssText = 'width:1440px;height:720px;display:block';
  full.getContext('2d').drawImage(render.domElement, 0, 0); document.body.appendChild(full);
  const strip = document.createElement('canvas'); strip.width = actors.map.size * 120; strip.height = 160;
  strip.style.cssText = 'width:' + actors.map.size * 60 + 'px;height:80px;display:block'; const ctx = strip.getContext('2d');
  const small = new THREE.Scene(); small.background = new THREE.Color('#D9EEEC'); small.add(ground.clone());
  LOOK3.setupScene(small, render, { extent: 2 }).update(new THREE.Vector3());
  const cam = new THREE.OrthographicCamera(-1.08, 1.08, 1.44, -1.44, .1, 60);
  cam.position.set(8, 8, 12); cam.lookAt(0, .65, 0); cam.updateMatrixWorld(); render.setSize(60, 80);
  let index = 0;
  for (const [id, actor] of actors.map) {
    const body = actor.h.object3d.clone(); body.position.set(0,0,0); body.rotation.y = -.38; small.add(body);
    const ring = id === holder.id ? fx.bounty[0].clone() : null;
    if (ring) { ring.position.set(0,.05,0); small.add(ring); }
    render.render(small, cam); ctx.drawImage(render.domElement, index++ * 120, 0);
    small.remove(body); if (ring) small.remove(ring);
  }
  render.domElement.hidden = true; document.body.appendChild(strip);
  return { ok: true, checks, worn, floor: fx.floor.size, holder: holder.id, renderer: render.info.render };
}
