// The stage: renderer, the iso camera, the B1 three-band toon light under the Candle Atoll sun, and the island.
// Lights and materials come from the approved look (art/look3.js, treatment 'cel'); the island is Candle Atoll (board AD c):
// a cream plateau ringed by candlestick cliffs, mint where the hour rose and coral where it fell.
// Sim milli-tiles reach the scene only through arena/frame.mjs.
import * as THREE from 'three';
import { ARENA_RADIUS_MILLI, MILLI } from './frame.mjs';

export const ISLAND_R = 15.5;            // plateau radius in tiles: the ring (12) plus the bench shore
export const ELEV_DEG = 35.264;
export const AZ_DEG = 45;
const AZ = AZ_DEG * Math.PI / 180;

const COL = { up: '#9FDCC5', upDeep: '#5FB79A', down: '#F6A796', downDeep: '#D97A6E', top: '#F7F0DC', topSide: '#E8D9B5',
  sea: '#BFE6EA', foam: '#FFF8EA', bg: '#D9EEEC' };

function rng(seed) { let s = seed >>> 0; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const flat = (c) => new THREE.MeshLambertMaterial({ color: new THREE.Color(c), flatShading: true });

function series(n) { // the hour's price: a seeded walk with a pump and a dump, so the far rim reads as a chart
  const r = rng(417); let p = 1.2; const out = [];
  for (let i = 0; i < n; i++) {
    const drift = i < n * 0.55 ? 0.09 : i < n * 0.7 ? 0.16 : -0.32, o = p, c = Math.max(0.6, p + drift * 1.4 + (r() - 0.5) * 0.9);
    out.push({ o, c, hi: Math.max(o, c) + 0.1 + r() * 0.3, lo: Math.min(o, c) - 0.1 - r() * 0.25 }); p = c;
  }
  return out;
}

function candle(k, base, scale, w) {
  const g = new THREE.Group(), up = k.c >= k.o, deep = up ? COL.upDeep : COL.downDeep;
  const y0 = base + Math.min(k.o, k.c) * scale, y1 = Math.max(y0 + 0.3, base + Math.max(k.o, k.c) * scale), hi = Math.max(y1 + 0.12, base + k.hi * scale);
  const box = (bw, ya, yb, color) => { const m = new THREE.Mesh(new THREE.BoxGeometry(bw, Math.max(0.04, yb - ya), bw), flat(color)); m.position.y = (ya + yb) / 2; m.castShadow = m.receiveShadow = true; g.add(m); return m; };
  const mixc = (a, b, t) => '#' + new THREE.Color(a).lerp(new THREE.Color(b), t).getHexString();
  box(w * 0.94, -3.2, y0, mixc(deep, COL.topSide, 0.45));
  box(w, y0, y1, up ? COL.up : COL.down);
  box(w * 1.03, y1, y1 + 0.08, deep);
  box(0.16, y1 + 0.08, hi, deep);
  return g;
}

function jitter(geo, amt, seed) {
  const p = geo.attributes.position, r = rng(seed), memo = new Map();
  for (let i = 0; i < p.count; i++) {
    const key = p.getX(i).toFixed(3) + ',' + p.getY(i).toFixed(3) + ',' + p.getZ(i).toFixed(3);
    if (!memo.has(key)) memo.set(key, [(r() - 0.5) * amt, (r() - 0.5) * amt * 0.6, (r() - 0.5) * amt]);
    const m = memo.get(key); p.setXYZ(i, p.getX(i) + m[0], p.getY(i) + m[1], p.getZ(i) + m[2]);
  }
  geo.computeVertexNormals(); return geo;
}

function grainTexture() {
  const n = 256, cv = document.createElement('canvas'); cv.width = cv.height = n;
  const g = cv.getContext('2d'), im = g.createImageData(n, n), r = rng(77);
  for (let i = 0; i < n * n; i++) { const x = i % n, y = (i / n) | 0, v = 236 + r() * 19 - ((x * 7 + y * 3) % 23 === 0 ? 10 : 0); im.data[i * 4] = im.data[i * 4 + 1] = im.data[i * 4 + 2] = v; im.data[i * 4 + 3] = 255; }
  g.putImageData(im, 0, 0);
  const t = new THREE.CanvasTexture(cv); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(5, 5); t.colorSpace = THREE.SRGBColorSpace; return t;
}

function foam(r, y, w) { const m = new THREE.Mesh(new THREE.TorusGeometry(r, w, 3, 48), new THREE.MeshBasicMaterial({ color: COL.foam })); m.rotation.x = Math.PI / 2; m.position.y = y; return m; }

export function buildIsland() {
  const g = new THREE.Group(), R = ISLAND_R, rnd = rng(9);
  const top = new THREE.Mesh(new THREE.CylinderGeometry(R, R + 0.3, 0.5, 40, 1), [flat(COL.topSide), flat(COL.top), flat(COL.topSide)]);
  top.position.y = -0.25; top.receiveShadow = true; g.add(top);
  const cliff = new THREE.Mesh(new THREE.CylinderGeometry(R + 0.3, R + 0.9, 2.4, 40, 2), flat(COL.topSide)); cliff.position.y = -1.7; cliff.receiveShadow = true; g.add(cliff);
  // faceted flagstones, near the rim only: the ring's middle stays quiet ground for the fight
  for (let i = 0; i < 46; i++) {
    const a = rnd() * Math.PI * 2, d = 12.6 + rnd() * 2.2, s = new THREE.Mesh(new THREE.CylinderGeometry(0.7 + rnd() * 0.8, 0.8 + rnd() * 0.8, 0.04, 5 + (i % 3)), flat(i % 4 ? '#F1E6C9' : '#EADBB8'));
    s.position.set(Math.cos(a) * d, 0.005, Math.sin(a) * d); s.rotation.y = rnd() * 3; s.receiveShadow = true; g.add(s);
  }
  // mint shrubs and sandstone rocks on the shore, never inside the ring
  for (let j = 0; j < 30; j++) {
    const b = rnd() * Math.PI * 2, e = 13.2 + rnd() * 1.6, shrub = j % 3 !== 2;
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(shrub ? 0.4 + rnd() * 0.25 : 0.3 + rnd() * 0.2, 0), flat(shrub ? (j % 2 ? COL.up : COL.upDeep) : COL.topSide));
    m.scale.y = shrub ? 0.9 : 0.6; m.position.set(Math.cos(b) * e, shrub ? 0.25 : 0.1, Math.sin(b) * e); m.rotation.set(rnd(), rnd() * 3, rnd()); m.castShadow = m.receiveShadow = true; g.add(m);
  }
  // the arena edge, drawn as a low foam-white band so the ring reads without a wall
  const ring = new THREE.Mesh(new THREE.RingGeometry(ARENA_RADIUS_MILLI / MILLI + 0.05, ARENA_RADIUS_MILLI / MILLI + 0.28, 96), new THREE.MeshBasicMaterial({ color: COL.foam, transparent: true, opacity: 0.8 }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.012; g.add(ring);
  // the candle rim: the far arc (top of the frame) is tall and reads as the chart; the near arc stays low so it never hides a fighter
  const N = 44, S = series(N), camAz = AZ;
  const farDir = new THREE.Vector3(-Math.sin(camAz), 0, -Math.cos(camAz)), leftScreen = new THREE.Vector3(-Math.cos(camAz), 0, Math.sin(camAz));
  const order = [];
  for (let i = 0; i < N; i++) { const a = i / N * Math.PI * 2, v = new THREE.Vector3(Math.cos(a), 0, Math.sin(a)); order.push({ v, far: v.dot(farDir), left: v.dot(leftScreen) }); }
  const far = order.filter((o) => o.far > -0.15).sort((p, q) => q.left - p.left), near = order.filter((o) => o.far <= -0.15);
  const w = 2.3 * Math.PI * (R + 0.7) / N / 1.15;
  far.forEach((o, i) => { const c = candle(S[Math.min(N - 1, i)], -3.4, 2.1, w); c.position.copy(o.v).multiplyScalar(R + 0.7); g.add(c); o.c = c; });
  near.forEach((o, i) => { const c = candle({ o: 0.9, c: 0.9 + (i % 2 ? 0.18 : -0.12), hi: 1.2, lo: 0.7 }, -3.3, 0.9, w); c.position.copy(o.v).multiplyScalar(R + 0.7); g.add(c); });
  // sea and foam
  const sg = new THREE.PlaneGeometry(140, 140, 70, 70); sg.rotateX(-Math.PI / 2);
  { const p = sg.attributes.position, r = rng(3); for (let i = 0; i < p.count; i++) p.setY(i, (r() - 0.5) * 0.12); sg.computeVertexNormals(); }
  const sea = new THREE.Mesh(sg, new THREE.MeshLambertMaterial({ color: COL.sea, flatShading: true })); sea.position.y = -1.9; sea.receiveShadow = true; g.add(sea);
  g.add(foam(R + 1.35, -1.88, 0.14)); g.add(foam(R + 2.4, -1.88, 0.07));
  // craft pass: hand-jitter and grain on every faceted mesh
  const grain = grainTexture(); let seed = 11;
  g.traverse((o) => {
    if (!o.isMesh || o.material.isMeshBasicMaterial || o.material.isArray) return;
    if (o.geometry.type === 'BoxGeometry') jitter(o.geometry, 0.07, seed++);
    if (o.geometry.attributes.uv && !Array.isArray(o.material)) { o.material.map = grain; o.material.needsUpdate = true; }
  });
  mergeStatic(g);
  return g;
}

// The island is static: its ~250 small meshes become a handful, one per material. Fewer draw calls in the colour pass and the
// shadow pass is the budget test's cheapest lever (§4.7 asks for static geometry merged or instanced once).
function mergeStatic(group) {
  group.updateMatrixWorld(true);
  const inv = new THREE.Matrix4().copy(group.matrixWorld).invert(), buckets = new Map(), drop = [];
  group.traverse((o) => {
    if (!o.isMesh || Array.isArray(o.material) || o.material.isMeshBasicMaterial || !o.geometry.attributes.position) return;
    const m = o.material, key = [m.type, m.color.getHexString(), !!m.flatShading, !!m.map, o.castShadow, o.receiveShadow].join('|');
    if (!buckets.has(key)) buckets.set(key, { material: m, cast: o.castShadow, receive: o.receiveShadow, meshes: [] });
    buckets.get(key).meshes.push(o); drop.push(o);
  });
  for (const b of buckets.values()) {
    const pos = [], nor = [], uv = [];
    for (const o of b.meshes) {
      const geo = (o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone()); geo.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld));
      if (!geo.attributes.normal) geo.computeVertexNormals();
      pos.push(...geo.attributes.position.array); nor.push(...geo.attributes.normal.array);
      uv.push(...(geo.attributes.uv ? geo.attributes.uv.array : new Float32Array(geo.attributes.position.count * 2)));
      geo.dispose();
    }
    const merged = new THREE.BufferGeometry();
    merged.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); merged.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3)); merged.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    const mesh = new THREE.Mesh(merged, b.material); mesh.castShadow = b.cast; mesh.receiveShadow = b.receive; mesh.name = 'island-merged'; group.add(mesh);
  }
  for (const o of drop) { o.parent.remove(o); o.geometry.dispose(); }
}

export function createStage(canvas, LOOK3, opts = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(opts.dprForce || Math.min(window.devicePixelRatio || 1, opts.dprCap || 2)); // dprForce lets the budget test render at DPR 2 on a 1.5 display
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(COL.bg);
  scene.fog = new THREE.Fog(new THREE.Color(COL.bg), 90, 140);
  LOOK3.setTreatment('cel');
  const lights = LOOK3.setupScene(scene, renderer, { extent: 19 });
  // coin-light: a low gold sun from the left, a cool mint sky (board AD c)
  lights.key.color.set('#FFD98F'); lights.key.intensity = 2.5;
  lights.fill.color.set('#D3F1E6'); if (lights.fill.groundColor) lights.fill.groundColor.set('#E8D8B0'); lights.fill.intensity = 1.85;
  lights.dir.set(-0.62, 0.95, 0.5).normalize();
  lights.key.shadow.mapSize.set(opts.shadowMap || 1024, opts.shadowMap || 1024);
  lights.update(new THREE.Vector3(0, 0, 0));
  const island = buildIsland(); scene.add(island);

  const camera = new THREE.OrthographicCamera(-20, 20, 12, -12, 0.1, 400);
  const view = { w: 0, h: 0, ppt: 30, narrow: false, elev: ELEV_DEG, panPx: 0 };

  function placeCamera(shakeX = 0, shakeY = 0) {
    const e = view.elev * Math.PI / 180, dir = new THREE.Vector3(Math.sin(AZ) * Math.cos(e), Math.sin(e), Math.cos(AZ) * Math.cos(e));
    camera.position.copy(dir).multiplyScalar(80); camera.up.set(0, 1, 0); camera.lookAt(0, 0, 0);
    if (shakeX || shakeY) { const r = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0), u = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1); camera.position.addScaledVector(r, shakeX).addScaledVector(u, shakeY); }
    camera.updateMatrixWorld();
  }
  // pads (optional, {top, bottom} in px): the free band to centre the ring in, e.g. a phone with board 1's panel open, where
  // the canvas ends at the panel's top and the sign covers its top (the scale stays the phone's: the ring's middle shows)
  function resize(w, h, pads) {
    view.w = w; view.h = h; view.narrow = w < 700;
    renderer.setSize(w, h, false);
    // fit the arena ring (12 tiles) plus the bench shore into the width; on a phone, crop the island's sides rather than shrink the fighters
    view.elev = view.narrow ? 52 : ELEV_DEG;
    const spanX = view.narrow ? 2 * 10.5 : 2 * 18, e = view.elev * Math.PI / 180;
    const spanY = 2 * (15.4 * Math.sin(e) + 3.2 * Math.cos(e));
    const topPad = pads ? pads.top : view.narrow ? 110 : 20, botPad = pads ? pads.bottom : view.narrow ? 150 : 20;
    view.ppt = view.narrow ? w / spanX : Math.min(w / spanX, (h - topPad - botPad) / spanY);
    camera.left = (-w / 2 + view.panPx) / view.ppt; camera.right = (w / 2 + view.panPx) / view.ppt; camera.top = h / 2 / view.ppt; camera.bottom = -h / 2 / view.ppt;
    placeCamera();
    // shift the view so the island's centre sits between the top and bottom pads
    // (the default phone pads keep their approved look; with explicit pads the centre goes to the middle of the free band:
    // raising the frustum by (bottom - top)/2 puts the island's centre (top + h - bottom)/2 from the canvas's top)
    const dy = (pads ? botPad - topPad : topPad - botPad) / 2 / view.ppt; camera.top -= dy; camera.bottom -= dy;
    camera.updateProjectionMatrix();
  }
  // shift the picture left by px screen pixels (board 1's panel is open on the right: the ring stays in the free part)
  function setPan(px) {
    if (Math.abs(px - view.panPx) < 0.25) return;
    const d = (px - view.panPx) / view.ppt; view.panPx = px;
    camera.left += d; camera.right += d; camera.updateProjectionMatrix();
  }
  return { THREE, renderer, scene, camera, lights, view, island, resize, placeCamera, setPan };
}
