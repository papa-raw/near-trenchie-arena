// Small pictures for the HUD: an item's own picture for the legendary floor sign (Pat's item 35: "with a small picture of
// the item") and a trenchie's face for the wall sign. Items are drawn by the same adapter as the arena (items3d.js) into
// one small offscreen renderer, once per item row; house faces are the stored reference renders of the house models
// (art/ref/b3-v34); a player's face is the snap-in guide's own portrait still (snapin/art/portrait.js), drawn once per look.
import * as THREE from 'three';

let R = null;
function renderer(px) {
  if (!R) { R = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true }); R.setClearColor(0x000000, 0); }
  R.setPixelRatio(1); R.setSize(px, px, false); return R;
}

const items = new Map();
/** A data URL of the item, framed to fit a px x px square; null if it cannot be drawn (no WebGL). */
export function itemStill(itemRenderer, LOOK3, row, px = 64) {
  if (items.has(row)) return items.get(row);
  let url = null;
  try {
    const r = renderer(px), scene = new THREE.Scene();
    const lights = LOOK3 && LOOK3.setupScene ? LOOK3.setupScene(scene, r, { extent: 1.2 }) : null;
    if (lights) { lights.dir.set(0.3, 4.2, 4.2).normalize(); lights.update(new THREE.Vector3(0, 0, 0)); }
    else { scene.add(new THREE.AmbientLight(0xffffff, 1.2)); const d = new THREE.DirectionalLight(0xffffff, 1.4); d.position.set(1, 3, 2); scene.add(d); }
    const g = itemRenderer.build(row); scene.add(g);
    const box = new THREE.Box3().setFromObject(g), size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    const half = Math.max(size.x, size.y, size.z, 0.05) * 0.62;
    const cam = new THREE.OrthographicCamera(-half, half, half, -half, 0.01, 50);
    cam.position.set(c.x + half * 3, c.y + half * 2.4, c.z + half * 3); cam.lookAt(c);
    r.render(scene, cam); url = r.domElement.toDataURL('image/png');
    scene.remove(g);
  } catch (e) { console.warn('item picture unavailable for ' + row, String(e)); }
  items.set(row, url); return url;
}

export const houseFace = (id) => './art/ref/b3-v34/' + id + '.png';

const faces = new Map();
/** A player's face from its persona look (the snap-in portrait); null until portrait.js is on the page, or if it fails. */
export function playerFace(player) {
  const SKP = globalThis.SKP;
  if (!player || !SKP || typeof SKP.portrait !== 'function') return null;
  const key = player.trenchieId + '|' + JSON.stringify(player.look || null) + '|' + (player.paletteIds || []).join(',');
  if (faces.has(key)) return faces.get(key);
  let url = null;
  try { url = SKP.portrait(player.look ? { s3: player.look, w: 96, h: 96, dpr: 1, ground: false } : { palette: player.paletteIds, w: 96, h: 96, dpr: 1, ground: false }); }
  catch (e) { console.warn('player face unavailable for ' + player.trenchieId, String(e)); }
  faces.set(key, url); return url;
}
