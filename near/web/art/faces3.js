/* faces3.js — one cartoon face per trenchie (ES module). Each face is a stylised caricature built from words (hair,
 * glasses, brows, mouth, skin, expression); no photo traced, spoof ids only. The face stays unlit, clear of items.
 */
import { LOOK3 as L } from './look3.js';
(function () {
  'use strict';
  var SKIN = { light: '#FBE7D6', warm: '#F3D2B3', tan: '#E4B993', deep: '#C79870' };
  var F = {
    'satrenchi':          { skin: '#2F2A26', eyes: 'glow', mouth: 'none' },                                       // perfect, keep as v3                                       // faceless hood, two soft lights
    'captain-banana-zone': { skin: SKIN.warm, eyes: 'dot', glasses: 'round', mouth: 'grin', hair: 'bald' },
    'vitrenchik':         { skin: SKIN.light, eyes: 'dot', ears: true, mouth: 'smile', hideHead: true, sigHat: true },              // the unicorn hat (sig piece) carries him
    'laser-sailor':       { skin: SKIN.light, eyes: 'laser', mouth: 'flat' },                      // keep the captain's cap
    'tommy-leeth':        { skin: SKIN.warm, eyes: 'dot', glasses: 'square', mouth: 'beam', hideHead: true, sigHat: true },
    'trenchtoly':         { skin: SKIN.warm, eyes: 'dot', mouth: 'talk', hair: 'cap-black', hideHead: true },
    'kathie-moonwood':    { skin: SKIN.light, eyes: 'dot', glasses: 'square', hair: 'bob', hairColor: '#E2C48E', mouth: 'smile', hideHead: true },
    'illia-trenchukhin':  { skin: SKIN.light, eyes: 'dot', mouth: 'calm', hideHead: true, sigHat: true },
    'eddie-lazertrench':  { skin: SKIN.light, eyes: 'dot', glasses: 'round', hair: 'short', hairColor: '#3B2F25', brows: 'flat', mouth: 'flat' },
    'mert-mumtrench':     { skin: SKIN.tan, eyes: 'dot', brows: 'flat', hair: 'bald-skin', mouth: 'teeth', gag: 'blah', maskW: 0.205, maskH: 0.17, maskDY: 0.03 },  // v3.3: skin scalp + shine, white grin (v3.4: no facial hair on any trenchie)
    'avichad':            { skin: SKIN.tan, eyes: 'dot', glasses: 'square', hair: 'tousled', hairColor: '#2E2620', mouth: 'laugh', hideHead: true },
    'kain-warrior':       { skin: SKIN.warm, eyes: 'dot', hair: 'spiky', hairColor: '#5A4A3C', mouth: 'smirk', hideHead: true },
    'hameme-pumpeshi':    { skin: SKIN.tan, eyes: 'dot', hair: 'bald', brows: 'raised', mouth: 'flat' },
    'stepan-gershunode':  { skin: SKIN.light, eyes: 'dot', glasses: 'round', hair: 'receding', hairColor: '#7A5B40', mouth: 'smile', hideHead: true, back: true }   // keep the drone
  };
  L.FACES = F;
  L.FACES3 = 'faces3 v0.1 (B3 v3) 2026-11-03';
})();
export const FACES = L.FACES;
