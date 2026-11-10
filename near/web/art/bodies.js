/* bodies.js — the six body presets (cosmetic only: every shape fights the same) and the starter kit's drawings.
 * A preset is B1's gumdrop lathe with its width, squareness, top and base flare changed and the height kept,
 * so the face, hats and hands still sit on it. `sy` scales the whole body from the ground (face and kit ride along).
 * look3 reads BODY live while it builds, so a preset is applied for the duration of one build and restored at once.
 */
import * as THREE from 'three';
import { LOOK3 as L } from './look3.js';
import { FACES } from './faces3.js';
import './items3.js';

const K = L.kit, FACE = K.FACE, BODY = K.BODY, M = K.M;
const TOP = BODY.H - FACE.y, CROWN = 0.082;
function crownR(dy) { return K.radiusAt(FACE.y + dy); }

export const SHAPES = {
  gumdrop:  { R: 0.226, n: 2.7, flare: 0.035, e: 2.1, sy: 1 },      // B1's approved body
  bean:     { R: 0.172, n: 2.4, flare: 0.0,   e: 2.4, sy: 1.12 },   // tall and slim
  dumpling: { R: 0.29,  n: 3.0, flare: 0.1,   e: 1.9, sy: 0.84 },   // short and wide
  pear:     { R: 0.188, n: 2.4, flare: 0.58,  e: 2.1, sy: 1 },      // the weight at the bottom
  pebble:   { R: 0.232, n: 5.0, flare: 0.0,   e: 3.0, sy: 0.94 },   // a soft box
  acorn:    { R: 0.252, n: 2.6, flare: -0.4,  e: 2.6, sy: 1.04 }    // the weight at the top
};
export const PRESET_IDS = Object.keys(SHAPES);
export const TONES = { light: '#FBE7D6', warm: '#F3D2B3', tan: '#E4B993', deep: '#C79870' };
export const PRESET_DEFAULT = { shape: 'gumdrop', body: 'p07', tone: 'warm', hat: 'st-cap' };

// ---- the starter kit's drawings ----
// Sun Cap: a peach dome that follows the wearer's own profile, a coral bill and button
L.registerItem('st-cap', function () {
  const g = new THREE.Group(); g.name = 'item:st-cap'; g.rotation.x = -0.1; g.userData.natural = 'head';
  const r = crownR(CROWN) + 0.012;
  const pts = [];
  for (let i = 0; i <= 14; i++) { const dy = CROWN + (TOP - 0.012 - CROWN) * i / 14; pts.push(new THREE.Vector2(crownR(dy) + 0.012, dy)); }
  pts.push(new THREE.Vector2(crownR(TOP - 0.03) * 0.55 + 0.012, TOP + 0.022)); pts.push(new THREE.Vector2(0.0001, TOP + 0.03));
  const dome = M(new THREE.LatheGeometry(pts, 64), 'p14'); dome.material.side = THREE.DoubleSide;
  const bill = M(new THREE.CylinderGeometry(r * 0.95, r * 0.95, 0.016, 40, 1, false, -Math.PI * 0.42, Math.PI * 0.84), 'p15');
  bill.scale.z = 1.55; bill.position.set(0, CROWN + 0.004, 0.012);
  const btn = M(new THREE.SphereGeometry(0.02, 14, 10), 'p15'); btn.position.y = TOP + 0.03;
  g.add(dome, bill, btn); return g;
});
// Beach Tee: a sand tee with one sky stripe (a two-tone split)
L.registerItem('st-tee', function () {
  const N = 256, cv = document.createElement('canvas'); cv.width = cv.height = N; const g = cv.getContext('2d');
  const y = (f) => (1 - K.vAt(f * BODY.H)) * N;
  g.fillStyle = L.C('p05'); g.fillRect(0, y(0.36), N, y(0.06) - y(0.36));
  g.fillStyle = L.C('p09'); g.fillRect(0, y(0.24), N, y(0.19) - y(0.24));
  const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
  const geo = K.heightShade(K.bodyGeo(Math.PI, Math.PI * 2), BODY.H);
  const m = new THREE.Mesh(geo, K.mat('#FFFFFF', { vc: true })); m.material.map = tex; m.material.alphaTest = 0.5; m.castShadow = false; m.receiveShadow = true;
  m.scale.set(1.014, 1, 1.014); m.name = 'item:st-tee';
  const grp = new THREE.Group(); grp.add(m); grp.userData.natural = 'body'; return grp;
});
// Driftwood Bonk: a pale, bent stick with one knot
L.registerItem('st-bonk', function () {
  const g = new THREE.Group(); g.name = 'item:st-bonk';
  const curve = new THREE.CatmullRomCurve3([new THREE.Vector3(0, -0.04, 0), new THREE.Vector3(0.012, 0.12, 0), new THREE.Vector3(-0.01, 0.26, 0), new THREE.Vector3(0.02, 0.36, 0)]);
  const stick = M(new THREE.TubeGeometry(curve, 24, 0.024, 12, false), 'p02');
  const tip = M(new THREE.SphereGeometry(0.034, 16, 12), 'p02'); tip.position.set(0.02, 0.36, 0);
  const knot = M(new THREE.SphereGeometry(0.016, 12, 8), 'p03'); knot.position.set(0.02, 0.2, 0.012);
  g.add(stick, tip, knot);
  g.rotation.set(0.1, 0, 0.3 + 0.14 + 0.3); g.position.y = -0.02; g.scale.setScalar(0.95);
  return g;
});

let nPreset = 0;
/** One preset body in the starter kit. look: { shape, body (palette id), tone (light|warm|tan|deep), hat (item id | 'hide') }. */
export function makePreset(look) {
  look = Object.assign({}, PRESET_DEFAULT, look || {});
  const SH = SHAPES[look.shape] || SHAPES.gumdrop, id = 'preset-' + (nPreset++);
  FACES[id] = { skin: TONES[look.tone] || TONES.warm, eyes: 'dot', mouth: 'smile' };
  const kit = { weapon: 'st-bonk', body: 'st-tee', trinket: 'st-roll' };
  if (look.hat !== 'hide') kit.head = look.hat;
  const keep = { R: BODY.R, n: BODY.n, flare: BODY.flare, e: BODY.e };
  let t;
  Object.assign(BODY, { R: SH.R, n: SH.n, flare: SH.flare, e: SH.e });
  try { t = L.makeTrenchie({ trenchieId: id, paletteIds: [look.body, 'p04'], kit }); }
  finally { Object.assign(BODY, keep); delete FACES[id]; }
  if (SH.sy !== 1) t.joints.base.scale.y = SH.sy;   // the contact shadow sits on root, outside base, so it stays flat
  t.object3d.userData.preset = look.shape; t.look = look;
  return t;
}
