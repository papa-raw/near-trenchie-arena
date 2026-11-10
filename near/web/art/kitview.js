// kitview.js — the shared look at kit items: one renderer, one light, a worn view, a floor view and the 60 px game-size view.
import * as THREE from 'three';
import { makePreset, setupLight, PRESET_IDS, makeHouse } from './index.js';
import { wear, onFloor } from './kit3d.js';

export const S = 300, DPR = 2, errors = [];
addEventListener('error', (e) => errors.push(String(e.message)));
const origErr = console.error; console.error = function () { errors.push([].join.call(arguments, ' ')); origErr.apply(console, arguments); };

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(DPR); renderer.setClearColor(new THREE.Color('#ECEEEA'), 1);
const scene = new THREE.Scene(); setupLight(scene, renderer, { extent: 1.4 });
const BODY_COLS = ['p09', 'p11', 'p12', 'p14', 'p07', 'p10'], TONES = ['warm', 'light', 'tan', 'deep', 'warm', 'light'];
export function pickWearer(avoid, i) { const bad = [].concat(avoid); for (let j = 0; j < 6; j++) if (!bad.includes(BODY_COLS[(i + j) % 6])) return i + j; return i; }   // a wearer whose body is not the item's own colour
export function wearer(i) { const t = makePreset({ shape: PRESET_IDS[i % 6], body: BODY_COLS[i % 6], tone: TONES[i % 6], hat: 'hide' }); t.setItems({}); t.object3d.rotation.y = -0.38; return t; }
// worn: [centre, halfH, azimuth, elevation]
export const OLD_CAM = { head: [[0, 0.58, 0], 0.34, 14, 12], body: [[0, 0.33, 0], 0.48, 14, 14], weapon: [[-0.1, 0.34, 0.05], 0.5, 14, 14], trinket: [[0.1, 0.22, 0.1], 0.3, 52, 12] };   // the first kit's cameras, kept for the before column
export const CAM = { head: [[0, 0.58, 0], 0.34, 14, 12], body: [[0, 0.33, 0], 0.48, 14, 14], weapon: [[-0.1, 0.4, 0.05], 0.6, 14, 14], trinket: [[0.1, 0.22, 0.1], 0.3, 52, 12] };
export function view(root, size, centre, halfH, az, el) {
  renderer.setSize(size, size, false); scene.add(root);
  const a = az * Math.PI / 180, e = el * Math.PI / 180, c = new THREE.Vector3().fromArray(centre);
  const cam = new THREE.OrthographicCamera(-halfH, halfH, halfH, -halfH, 0.1, 60);
  cam.position.set(c.x + Math.sin(a) * Math.cos(e) * 20, c.y + Math.sin(e) * 20, c.z + Math.cos(a) * Math.cos(e) * 20); cam.lookAt(c);
  renderer.render(scene, cam);
  const cv = document.createElement('canvas'); cv.width = size * DPR; cv.height = size * DPR; cv.getContext('2d').drawImage(renderer.domElement, 0, 0);
  scene.remove(root); return cv;
}
export function worn(slot, build, tier, i, size, cam) {
  const t = wearer(i); wear(t, build(), tier); const [c, hh, az, el] = (cam || CAM)[slot];
  const cv = view(t.object3d, size || S, c, hh, az, el); t.dispose(); return cv;
}
export function floor(build, tier, size, opts) { const f = onFloor(build(), tier, opts); return view(f, size || S, [0, 0.4, 0], 0.55, 24, 26); }
export function gameSize(build, tier, i) {   // one 60 px body, whole
  const t = wearer(i); wear(t, build(), tier); const cv = view(t.object3d, 60, [0, 0.36, 0], 0.54, 30, 28); t.dispose(); return cv;
}
/** A house model for the craft bar: whole, at 60 px or larger. */
export function house(id, size) { const t = makeHouse(id, { kit: 'full' }); t.object3d.rotation.y = -0.38; const cv = view(t.object3d, size, [0, size > 100 ? 0.36 : 0.36, 0], 0.54, size > 100 ? 24 : 30, size > 100 ? 18 : 28); t.dispose && t.dispose(); return cv; }
/** A house model standing in a tier-glow floor tile: the craft reference for the floor view. */
export function houseFloor(id, tier) {
  const t = makeHouse(id, { kit: 'full' }), f = onFloor(new THREE.Group(), tier, {});
  t.object3d.rotation.y = -0.38; f.add(t.object3d);
  const cv = view(f, S, [0, 0.4, 0], 0.55, 24, 26); f.remove(t.object3d); t.dispose && t.dispose(); return cv;
}
