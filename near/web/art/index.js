/* art/index.js — the house models and body presets, as one import.
 *   import { makeHouse, makePreset, HOUSE_IDS, PRESET_IDS, setupLight } from './art/index.js'
 * The page needs an import map for 'three' (see compare.html). Nothing here touches the DOM except the canvas
 * textures that look3 and the starter kit draw.
 */
import * as THREE from 'three';
import { LOOK3 } from './look3.js';
import { FACES } from './faces3.js';
import './items3.js';
import { ROSTER, ITEMS, RIVALS, ALLIANCES } from './roster.js';
import { SHAPES, PRESET_IDS, PRESET_DEFAULT, TONES, makePreset } from './bodies.js';

export { LOOK3, FACES, ROSTER, ITEMS, RIVALS, ALLIANCES, SHAPES, PRESET_IDS, PRESET_DEFAULT, TONES, makePreset };
export const HOUSE_IDS = ROSTER.map((r) => r.trenchieId);
export const KEY_DIR = [0.3, 4.2, 4.2];   // the approved key direction for characters

export function houseRow(id) { return ROSTER.find((r) => r.trenchieId === id) || null; }

/** The items shown on the approved roster board: the face, the weapon and the signature piece (plus a kept head piece). */
export function boardKit(r) {
  const fc = FACES[r.trenchieId] || {}, sp = r.signaturePiece, it = { weapon: r.kit.weapon };
  if (!fc.hideHead) it.head = r.kit.head;
  if (sp) it[sp.slot] = sp.id;
  if (fc.hideHead && sp && sp.slot === 'head' && !fc.sigHat) delete it.head;   // the named hats always show
  if (fc.back) it.trinket = r.kit.trinket;
  return Object.assign({}, r, { kit: it });
}

/** One house trenchie. opts.kit: 'board' (default, the approved look) or 'full' (all four slots worn). */
export function makeHouse(id, opts) {
  opts = opts || {};
  const r = houseRow(id);
  if (!r) throw new Error('makeHouse: unknown house id ' + id);
  return LOOK3.makeTrenchie(opts.kit === 'full' ? r : boardKit(r));
}

/** Lights and shadows for a scene (B1 three-band toon, the approved key direction). Returns {key, fill, dir, update}. */
export function setupLight(scene, renderer, opts) {
  opts = opts || {};
  LOOK3.setTreatment('cel');
  const lights = LOOK3.setupScene(scene, renderer, { extent: opts.extent || 1.2 });
  if (!opts.keepDir) lights.dir.set(KEY_DIR[0], KEY_DIR[1], KEY_DIR[2]).normalize();
  lights.update(opts.center || new THREE.Vector3(0, 0, 0));
  return lights;
}

export { applyMotion, install as installMotion, poseAt, duration as motionDuration, STATES as MOTION_STATES, WEAPONS as MOTION_WEAPONS } from './motion3.js';
