# near/web/art — the house models and body presets

ES modules for the 14 house trenchies and the six body presets, drawn in the approved three-band toon with one key light.
Load them through an import map for `three` (see `compare.html`).

```js
import { makeHouse, makePreset, setupLight, HOUSE_IDS, PRESET_IDS } from './art/index.js';
setupLight(scene, renderer);                       // lights and shadows (call once per scene)
const t = makeHouse('laser-sailor');               // the approved roster look; { kit: 'full' } wears all four slots
scene.add(t.object3d);                             // t.joints: root, base, pivot, head, face, handR, handL, mount*, footL, footR, shadow
const p = makePreset({ shape: 'pear', body: 'p07', tone: 'warm' });   // shapes: gumdrop bean dumpling pear pebble acorn
```

- `look3.js` the look: body, rig joints, materials, the scene light. `faces3.js` the 14 faces. `items3.js` the drawings of every item the 14 wear. `bodies.js` the six shapes and the starter kit. `roster.js` + `kits.js` the house rows and item records (generated from the lore kits).
- `motion3.js` key poses and timing on the RIG3 joints: `applyMotion(t, { state, weapon, age, facing })` is a pure function of its inputs (13 states, 6 weapons); `installMotion()` makes `t.setPose({...})` call it. `motion.html` draws every motion as eight frames.
- Units: 1 world unit = 1 tile, y up, local front = +z. `LOOK3.facingRotY(f)` maps sim facing 0..15 to `rotation.y`.
- `compare.html` draws each model next to its stored reference render (`ref/b3-v34/*.png`, 540x580 at DPR 2) and diffs the pixels. `node art-case.cjs` runs the same check headless.

## The item kit pages
- `kit.html` every menu row worn and on the floor with its tier glow, plus the extra kit shapes, and a 60 px strip per slot. `kit3d.js` draws an item from `near/items/kit.json`; body garments are refitted to each of the six body shapes, and on the floor a garment hangs on a small dress form so it always reads closed.
- `kit-compare.html` the eleven rebuilt items (Hawaiian Shirt, Wetsuit, Overalls, Robe, Poncho, Sash, Apron, Coconut Mortar, Jelly Zapper, Pocket Laser, Thump Shell) as the first kit drew them, as they are now, and next to a house model, at 60 px, 300 px and on the floor. `?i=3,4` draws just those items. `ref/kit-before-redo.json` is the first kit, kept only for the "before" column.
