/* kit3d.js — draws an item in the renderer-neutral format (near/items/kit.json, trenchie-item/3) as a three.js Group:
 * one toon material per palette id, and nothing in an item chooses a material, light or texture.
 * Item units are 2 per tile, angles are degrees, rotations apply X then Y then Z, a torus ring lies in the XZ plane, a tube
 * is stroked at `width`. A node with a `role` takes that role's colour when the row names one.
 *   const g = buildBase(kit, 'head/cap', { main: 'p14', accent: 'p15' });
 *   const g2 = buildMenuRow(kit, 'c-head-maxi');          // the menu row's base and colours
 *   const g3 = buildSpec(kit, spec);                       // a kit-built or free-drawn item spec
 */
import * as THREE from 'three';
import { LOOK3 } from './look3.js';
import { SHAPES } from './bodies.js';

const K = LOOK3.kit, UNIT = 0.5, RAD = Math.PI / 180;   // 1 item unit = 0.5 tile
const GEO = {
  sphere: (n) => new THREE.SphereGeometry(n.r, 24, 16),
  hemisphere: (n) => new THREE.SphereGeometry(n.r, 32, 14, 0, Math.PI * 2, 0, Math.PI / 2),
  cylinder: (n) => new THREE.CylinderGeometry(n.rTop === undefined ? n.r : n.rTop, n.r, n.h, 40, n.h > 0.1 ? 10 : 1, !!n.open, (n.arcStart || 0) * RAD, n.arc === undefined ? Math.PI * 2 : n.arc * RAD),
  cone: (n) => new THREE.ConeGeometry(n.r, n.h, 28),
  box: (n) => new THREE.BoxGeometry(n.w, n.h, n.d),
  torus: (n) => new THREE.TorusGeometry(n.r, n.tube, 10, 40, n.arc === undefined ? Math.PI * 2 : n.arc * RAD).rotateX(Math.PI / 2),
  tube: (n) => new THREE.TubeGeometry(new THREE.CatmullRomCurve3(n.points.map((p) => new THREE.Vector3(p[0], p[1], p[2])), false, 'catmullrom', 0.2), 24, n.width / 2, 8, false),
  plate: (n) => {
    const w = n.w, h = n.h, r = Math.min(n.radius || 0, w / 2, h / 2), x = -w / 2, y = -h / 2, s = new THREE.Shape();
    s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r); s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
    const g = new THREE.ExtrudeGeometry(s, { depth: n.t, bevelEnabled: false, curveSegments: 8 }); g.translate(0, 0, -n.t / 2); return g;
  }
};

function colorOf(n, colors) { return (n.role && colors[n.role]) || n.color; }
export function buildNode(n, colors) {
  if (n.type === 'group') { const g = new THREE.Group(); (n.children || []).forEach((c) => g.add(buildNode(c, colors))); place(g, n); return g; }
  if (!GEO[n.type]) throw new Error('kit3d: unknown primitive ' + n.type);
  const m = K.M(GEO[n.type](n), colorOf(n, colors), {});
  if (n.open || (n.arc !== undefined && n.type === 'cylinder')) m.material.side = THREE.DoubleSide;
  place(m, n); return m;
}
function place(o, n) {
  if (n.translate) o.position.fromArray(n.translate);
  if (n.rotate) o.rotation.set(n.rotate[0] * RAD, n.rotate[1] * RAD, n.rotate[2] * RAD, 'ZYX');   // X first, then Y, then Z
  if (n.scale !== undefined) { if (Array.isArray(n.scale)) o.scale.fromArray(n.scale); else o.scale.setScalar(n.scale); }
}
/** A garment shell that hugs the body (a cylinder whose ends sit near the body's own radius) is bent to follow the body's curve between its ends, so the egg never bulges through it. */
function contourShell(m, n) {
  if (n.type !== 'cylinder' || (n.rotate && n.rotate.some((a) => a))) return;
  const ys = (y) => Math.max(0.02, Math.min(BODY.H - 0.02, y)), yc = ((n.translate && n.translate[1]) || 0) * UNIT, h = n.h * UNIT, rb = n.r * UNIT, rt = (n.rTop === undefined ? n.r : n.rTop) * UNIT, y0 = yc - h / 2, y1 = yc + h / 2;
  const exB = rb - bodyR(ys(y0)), exT = rt - bodyR(ys(y1));
  if (Math.abs(exB) > 0.08 || Math.abs(exT) > 0.08 || h < 0.05) return;
  const pos = m.geometry.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const t = pos.getY(i) / n.h + 0.5, lin = rb + (rt - rb) * t; if (lin < 0.02) continue;
    const f = (bodyR(ys(y0 + t * h)) + exB + (exT - exB) * t) / lin; pos.setX(i, pos.getX(i) * f); pos.setZ(i, pos.getZ(i) * f);
  }
  pos.needsUpdate = true; m.geometry.computeVertexNormals(); m.geometry.computeBoundingSphere();
}
/** One base with a colour map { main, accent, trim } of palette ids (a base's own colours fill what is not given). */
export function buildBase(kit, id, colors, extraNodes) {
  const [slot, name] = id.split('/'), b = kit.bases[slot] && kit.bases[slot][name];
  if (!b) throw new Error('kit3d: unknown base ' + id);
  const col = Object.assign({}, b.colors, colors || {});
  const g = new THREE.Group(); g.name = 'kit:' + id; g.userData.kit = id; g.userData.slot = slot;
  b.nodes.concat(extraNodes || []).forEach((n) => { const m = buildNode(n, col); if (slot === 'body') contourShell(m, n); g.add(m); });
  g.scale.setScalar(UNIT); return g;
}
export function buildMenuRow(kit, rowId) {
  const r = kit.menu.find((x) => x.row === rowId); if (!r) throw new Error('kit3d: unknown menu row ' + rowId);
  const g = buildBase(kit, r.kit, r.colors); g.name = 'row:' + rowId; return g;
}
/** A kit-built item (spec.kit + spec.colors + decorations) or a free-drawn one (spec.nodes only). */
export function buildSpec(kit, spec) {
  if (spec.kit) { const g = buildBase(kit, spec.kit, spec.colors, spec.nodes); g.name = 'item:' + spec.id; return g; }
  const g = new THREE.Group(); g.name = 'item:' + spec.id; g.userData.slot = spec.slot;
  (spec.nodes || []).forEach((n) => g.add(buildNode(n, spec.colors || {}))); g.scale.setScalar(UNIT); return g;
}
const BH = 0.66, GUMDROP = SHAPES.gumdrop;
function profileR(S, y) {   // a body shape's radius at a height above its bottom (the lathe the renderer draws)
  const k = Math.max(-1, Math.min(1, 2 * y / BH - 1)), s = Math.sign(k) * Math.pow(Math.abs(k), S.e / 2), c = Math.sqrt(Math.max(0, 1 - s * s));
  return S.R * Math.pow(c, 2 / S.n) * (1 + S.flare * (1 - y / BH));
}
/** Refit a garment built for the gumdrop body to another body shape: shells are reshaped vertex by vertex, loose pieces move out or in with the profile. */
function fitBody(g, S, baseY) {
  baseY = baseY || 0;
  if (!S || S === GUMDROP) return;
  const ratio = (yTile) => { const y = Math.min(BH - 0.06, Math.max(0.06, yTile)); return profileR(S, y) / profileR(GUMDROP, y); };
  const v = new THREE.Vector3();
  g.children.forEach((m) => {
    m.updateMatrix();
    const t = m.geometry && m.geometry.type;
    if (t === 'CylinderGeometry' || t === 'TorusGeometry' || t === 'TubeGeometry') {
      const pos = m.geometry.attributes.position, inv = m.matrix.clone().invert();
      for (let i = 0; i < pos.count; i++) {
        v.fromBufferAttribute(pos, i).applyMatrix4(m.matrix); const f = ratio(v.y * UNIT + baseY); v.x *= f; v.z *= f; v.applyMatrix4(inv); pos.setXYZ(i, v.x, v.y, v.z);
      }
      pos.needsUpdate = true; m.geometry.computeVertexNormals(); m.geometry.computeBoundingSphere();
    } else {
      const f = ratio(m.position.y * UNIT + baseY); m.position.x *= f; m.position.z *= f;
      if (t === 'SphereGeometry' && m.geometry.parameters.thetaLength < 2) { m.scale.x *= f; m.scale.z *= f; }   // a dome widens with the body under it
    }
  });
}
const MOUNT = { head: 'mountHead', body: 'mountBody', weapon: 'mountWeapon', trinket: 'mountTrinket' };
const TIER_PLATE = { common: 'p06', rare: 'p10', legendary: 'p13' };
/** Put an item group on a trenchie (from LOOK3.makeTrenchie / makePreset). Weapons are held leaning out and hats sit a little back, like the roster's. */
export function wear(t, g, tier) {
  const slot = g.userData.slot, mount = t.joints[MOUNT[slot]], sh = SHAPES[t.object3d.userData.preset], fit = sh ? sh.R / SHAPES.gumdrop.R : 1;
  if (slot === 'head') fitBody(g, sh, BH * 0.62);                 // hats follow the wearer's own profile too (the head mount sits at eye height)
  if (slot === 'body') fitBody(g, sh);                            // garments follow the wearer's own profile, height by height
  if (slot === 'trinket') {
    const plate = K.M(new THREE.CylinderGeometry(0.046, 0.046, 0.012, 32), TIER_PLATE[tier || 'common'], {});
    plate.rotation.x = Math.PI / 2; plate.position.z = 0.004; g.position.y = -0.11;   // the kit lifts trinkets 0.11 tile so the box starts at y = 0
    const badge = new THREE.Group(); badge.add(plate, g); badge.scale.setScalar(1.3); badge.position.set(0.012, 0.045, -0.012); mount.add(badge); return g;   // a hip badge reads at game size when drawn 1.3x
  } else if (slot === 'weapon') {
    g.rotation.set(0.1, 0, 0.74); g.position.y = -0.02; g.scale.multiplyScalar(0.95);   // held out from the body, about 0.45 H
  } else if (slot === 'head') g.rotation.x = -0.1;
  mount.add(g); return g;
}

const BODY = { H: 0.66, R0: 0.226, N: 2.7, E: 2.1, FLARE: 0.035 };
function bodyR(y) {   // the body's own radius at a height above its bottom: the lathe the renderer draws
  const k = Math.max(-1, Math.min(1, 2 * y / BODY.H - 1)), s = Math.sign(k) * Math.pow(Math.abs(k), BODY.E / 2), c = Math.sqrt(Math.max(0, 1 - s * s));
  return BODY.R0 * Math.pow(c, 2 / BODY.N) * (1 + BODY.FLARE * (1 - y / BODY.H));
}
/** A wooden dress form shaped like the trenchie's own body, on a pole and a round foot: it closes a garment on the floor. In tile units, body bottom at y = 0.2. */
function dressForm() {
  const prof = [], top = 0.33;
  for (let i = 0; i <= 16; i++) { const y = top * i / 16; prof.push([Math.max(0.0005, bodyR(y) * 0.985), y]); }
  [[0.215, 0.36], [0.2, 0.395], [0.14, 0.43], [0.07, 0.46], [0.05, 0.49], [0.0005, 0.51]].forEach((p) => prof.push(p));
  const g = new THREE.Group(), body = K.M(new THREE.LatheGeometry(prof.map((p) => new THREE.Vector2(p[0], p[1])), 48), 'p02', {});
  const pole = K.M(new THREE.CylinderGeometry(0.02, 0.02, 0.2, 16), 'p01', {}), foot = K.M(new THREE.CylinderGeometry(0.11, 0.12, 0.024, 36), 'p01', {});
  body.position.y = 0.2; pole.position.y = 0.1; foot.position.y = 0.012;
  g.add(body, pole, foot); g.userData.dressForm = true; return g;
}

const GLOW = { common: 'p06', rare: 'p10', legendary: 'p13' };
let pillarTex = null, discTex = null;
function gradTex(kind) {
  const cv = document.createElement('canvas'); cv.width = cv.height = 128; const g = cv.getContext('2d');
  if (kind === 'pillar') { const gr = g.createLinearGradient(0, 0, 0, 128); gr.addColorStop(0, 'rgba(255,255,255,0)'); gr.addColorStop(0.5, 'rgba(255,255,255,0.3)'); gr.addColorStop(1, 'rgba(255,255,255,1)'); g.fillStyle = gr; g.fillRect(0, 0, 128, 128); }
  else { const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64); gr.addColorStop(0, 'rgba(255,255,255,0.9)'); gr.addColorStop(0.6, 'rgba(255,255,255,0.35)'); gr.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = gr; g.fillRect(0, 0, 128, 128); }
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; return t;
}
/** An item lying on the floor with its tier glow: a ring and a soft disc on the ground, a pillar of light, the item raised and shown. */
export function onFloor(g, tier, opts) {
  const root = new THREE.Group(), col = new THREE.Color(LOOK3.C(GLOW[tier || 'common']));
  pillarTex = pillarTex || gradTex('pillar'); discTex = discTex || gradTex('disc');
  const fx = (map, geo) => new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: col, map, transparent: true, opacity: 0.6, depthWrite: false, side: THREE.DoubleSide }));
  const disc = fx(discTex, new THREE.CircleGeometry(0.36, 40)); disc.rotation.x = -Math.PI / 2; disc.position.y = 0.004; root.add(disc);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.27, 0.02, 8, 48), new THREE.MeshBasicMaterial({ color: col })); ring.rotation.x = Math.PI / 2; ring.position.y = 0.008; root.add(ring);
  const pillar = fx(pillarTex, new THREE.CylinderGeometry(0.2, 0.26, 1.1, 32, 1, true)); pillar.position.y = 0.55; pillar.material.opacity = 0.5; root.add(pillar);
  const slot = g.userData.slot, item = new THREE.Group(); item.add(g);
  if (slot === 'body' && !(opts && opts.legacy)) g.position.y = 0.2;
  if (slot === 'weapon') { item.rotation.set(-Math.PI / 2 + 0.25, 0.5, 0.2); item.position.set(0.12, 0.3, 0.1); item.scale.setScalar(1.5); g.position.y = -0.16; }
  else if (slot === 'trinket') { item.rotation.set(-0.5, 0.4, 0); item.position.y = tier === 'legendary' ? 0.26 : 0.2; item.scale.setScalar(tier === 'legendary' ? 2.7 : 1.9); g.position.y = -0.11; const plate = K.M(new THREE.CylinderGeometry(0.046, 0.046, 0.012, 32), TIER_PLATE[tier || 'common'], {}); plate.rotation.x = Math.PI / 2; plate.position.z = 0.004; item.add(plate); }
  else if (slot === 'body') {
    if (opts && opts.legacy) { item.position.y = 0.04; item.scale.setScalar(0.9); item.rotation.y = 0.4; }   // the first kit's presentation: the bare shell
    else { item.add(dressForm()); item.position.y = 0.0; item.scale.setScalar(0.92); item.rotation.y = 0.4; }   // a garment is shown closed, on a wooden dress form with a stand
  }
  else { item.position.y = 0.0 - 0.082 * 1.5 + 0.03; item.scale.setScalar(1.5); item.rotation.y = 0.3; }   // head pieces stand on the floor on their own brim
  root.add(item); root.userData.glow = tier || 'common';
  return root;
}
