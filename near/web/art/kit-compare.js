// kit-compare.js — the eleven rebuilt kit items against the first kit's version of each and against the house models, at 60 px, 300 px and on the floor.
import { buildBase } from './kit3d.js';
import { errors, worn, floor, gameSize, house, houseFloor, OLD_CAM, pickWearer } from './kitview.js';
import { HOUSE_IDS } from './index.js';

const kit = await (await fetch('../../items/kit.json')).json();
const before = await (await fetch('ref/kit-before-redo.json')).json();
// [name, slot, tier, before base, after base, before colours, after colours, the brief: silhouette / three features / at 60 px]
const ITEMS = [
  ['Hawaiian Shirt', 'body', 'common', 'body/tee', 'body/hawaiian', { main: 'p07', accent: 'p14' }, { main: 'p08', accent: 'p14' },
    'A loose leaf-green shirt with short sleeves. Cream collar flaps, a salmon hem band, a print of five salmon and yellow flowers. At 60 px: a green body with bright dots.'],
  ['Wetsuit', 'body', 'common', 'body/suit', 'body/wetsuit', { main: 'p01', accent: 'p09' }, { main: 'p01', accent: 'p09' },
    'A dark suit with bright side panels. Short sleeves with blue cuffs, a collar ring, a zip with a gold pull. At 60 px: a dark body with two blue stripes down the sides.'],
  ['Overalls', 'body', 'common', 'body/overalls', 'body/overalls', { main: 'p10', accent: 'p12' }, { main: 'p10', accent: 'p12' },
    'Blue dungarees over a cream tee. A bib with a light pocket, two straps over the shoulders, two gold buttons. At 60 px: blue lower body, cream chest, two straps.'],
  ['Robe', 'body', 'rare', 'body/robe', 'body/robe', { main: 'p11', accent: 'p13' }, { main: 'p11', accent: 'p13' },
    'A long lavender drape that flares at the hem. Gold hem and belt with a knot and two tails, gold V trim, bell sleeves. At 60 px: a wide bell of lavender with a gold belt.'],
  ['Poncho', 'body', 'rare', 'body/poncho', 'body/poncho', { main: 'p07', accent: 'p13' }, { main: 'p07', accent: 'p13' },
    'A wide striped cape. A neck ring, gold and coral bands, a point at the front, a fringe along the hem. At 60 px: a wide triangle of mint with bands and a dotted hem.'],
  ['Sash', 'body', 'rare', 'body/sash', 'body/sash', { main: 'p15', accent: 'p12' }, { main: 'p15', accent: 'p12' },
    'A cream tunic with a wide coral sash slanting across the chest. A gold medal, a knot at the hip, two hanging tails. At 60 px: a coral diagonal on cream.'],
  ['Apron', 'body', 'rare', 'body/apron', 'body/apron', { main: 'p05', accent: 'p10' }, { main: 'p05', accent: 'p10' },
    'A cream apron over the front. A bib on a blue neck loop, a pocket with a spoon, a blue waist tie bowed at the hip. At 60 px: a cream front with blue ties.'],
  ['Coconut Mortar', 'weapon', 'common', 'weapon/bomb', 'weapon/mortar', { main: 'p03', accent: 'p12' }, { main: 'p03', accent: 'p12' },
    'A wooden barrel on a grip with a flared muzzle. Gold bands, a coconut with three eyes in the mouth, a lit fuse. At 60 px: a brown tube with a round nut on top and a red spark.'],
  ['Jelly Zapper', 'weapon', 'common', 'weapon/wand', 'weapon/jelly', { main: 'p11', accent: 'p09' }, { main: 'p11', accent: 'p12' },
    'A lavender jelly in a brass cup on a grip. A lighter core and a shine, a drip, two spark prongs with red tips. At 60 px: a big wobbly purple blob on a stick with two sparks.'],
  ['Pocket Laser', 'trinket', 'common', 'trinket/pen', 'trinket/pen', { main: 'p03', accent: 'p11' }, { main: 'p10', accent: 'p12' },
    'A blue pen torch tilted on the hip. A gold clip and band, a dark lens ring, a red tip and a short beam. At 60 px: a slanted blue stick with a red dot.'],
  ['Thump Shell', 'trinket', 'common', 'trinket/shell', 'trinket/shell', { main: 'p14', accent: 'p15' }, { main: 'p14', accent: 'p15' },
    'A flat pink shell with a cream rim. A coral spiral of one and a half turns, a spire tip, three yellow sound arcs. At 60 px: a pink disc with a spiral and yellow arcs.'],
  // second pass: the other kit items that did not read at 60 px
  ['Beach Tee', 'body', 'common', 'body/tee', 'body/tee', { main: 'p05', accent: 'p09' }, { main: 'p05', accent: 'p09' },
    'A roomy cream tee with short sleeves and a crew neck. A blue wave stripe at the hem and a sun on the chest. At 60 px: a cream body with a blue hem and a yellow dot.'],
  ['Life Vest', 'body', 'common', 'body/vest', 'body/vest', { main: 'p14', accent: 'p05' }, { main: 'p14', accent: 'p04' },
    'A bright orange life vest. A fat collar roll, two white reflective bands, a black belt strap with a gold buckle, a whistle. At 60 px: an orange torso with white stripes and a dark belt.'],
  ['Sweatband', 'head', 'common', 'head/sweatband', 'head/sweatband', { main: 'p14', accent: 'p15' }, { main: 'p15', accent: 'p04' },
    'A thick coral terry band round the forehead. Two white stripes, a white patch on the front, a knot with two tails at the side. At 60 px: a coral band with white stripes.'],
  ['Hard Hat', 'head', 'common', 'head/hardhat', 'head/hardhat', { main: 'p05', accent: 'p12' }, { main: 'p12', accent: 'p13' },
    'A bright yellow dome with a round brim. A centre ridge and a side rib, a front lamp. At 60 px: a yellow dome with a ridge and a white lamp.'],
  ['Neon Visor', 'head', 'rare', 'head/visor', 'head/visor', { main: 'p07', accent: 'p08' }, { main: 'p07', accent: 'p12' },
    'A wide mint sports band with a big yellow bill that juts out and tilts down, a white dot and a thin white stripe, open on top. At 60 px: a mint band with a yellow bill sticking out.'],
  ['Crown', 'head', 'rare', 'head/crown', 'head/crown', { main: 'p12', accent: 'p15' }, { main: 'p12', accent: 'p15' },
    'A tall gold band with five spikes tipped by coral beads. Three jewels on the band. At 60 px: a gold crown with dots on the points.'],
  ['Pebble Sling', 'weapon', 'common', 'weapon/sling', 'weapon/sling', { main: 'p03', accent: 'p14' }, { main: 'p03', accent: 'p14' },
    'A forked wooden handle with a thick coral rubber band and a leather pouch holding a big grey pebble. At 60 px: a brown Y with a grey stone.'],
  ['Narwhal Pike', 'weapon', 'common', 'weapon/spear', 'weapon/spear', { main: 'p05', accent: 'p10' }, { main: 'p05', accent: 'p10' },
    'A long shaft with gold rings. A round blue narwhal head with an eye and a pink spot, and its spiral tusk as the point. At 60 px: a blue ball on a stick with a long cream spike.'],
  ['Dodge Roll', 'trinket', 'common', 'trinket/roll', 'trinket/roll', { main: 'p05', accent: 'p10' }, { main: 'p05', accent: 'p10' },
    'A rolled sleeping mat seen end-on with a blue spiral and two straps, and a yellow arrow curling round it. At 60 px: a cream disc with a blue swirl.'],
  ['Static Sock', 'trinket', 'common', 'trinket/bolt', 'trinket/bolt', { main: 'p12', accent: 'p13' }, { main: 'p10', accent: 'p12' },
    'A blue sock with a white cuff and toe, kicking out two yellow sparks. At 60 px: a blue L with white ends and yellow zigzags.'],
  ['Fridge Magnet', 'trinket', 'common', 'trinket/magnet', 'trinket/fridge', { main: 'p15', accent: 'p06' }, { main: 'p15', accent: 'p06' },
    'A red horseshoe magnet with silver tips pinning a cream paper note with two scribbled lines. At 60 px: a red U on a cream square.'],
  ['Horseshoe Magnet', 'trinket', 'rare', 'trinket/magnet', 'trinket/magnet', { main: 'p15', accent: 'p06' }, { main: 'p15', accent: 'p06' },
    'A fat red U with silver tips and a little yellow spark. At 60 px: a red U.'],
  ['Bubble Wand', 'trinket', 'common', 'trinket/ring', 'trinket/ring', { main: 'p09', accent: 'p10' }, { main: 'p10', accent: 'p12' },
    'A blue loop on a gold handle blowing three round bubbles with shines. At 60 px: a blue ring and light-blue balls.'],
  ['Smoke Bomb', 'trinket', 'common', 'trinket/bomb', 'trinket/bomb', { main: 'p01', accent: 'p12' }, { main: 'p01', accent: 'p15' },
    'A black bomb with a grey cap and a lit fuse, puffing a cloud of cream and grey smoke. At 60 px: a black ball with a smoke puff and a red spark.'],
  ['Beanie', 'head', 'rare', 'head/beanie', 'head/beanie', { main: 'p10', accent: 'p09' }, { main: 'p10', accent: 'p09' },
    'A blue knit dome with five light ribs, a thick folded cuff with a gold stripe and a yellow woven patch, a two-tone pom. At 60 px: a blue cap with a fat light cuff and a fluffy pom.'],
  ['Lantern', 'weapon', 'rare', 'weapon/lens', 'weapon/lens', { main: 'p14', accent: 'p12' }, { main: 'p14', accent: 'p12' },
    'A pole with a hook; a hanging lantern with a base, four bars, a glowing yellow glass chamber and a red flame, a pointed salmon cap with a gold finial and a tassel. At 60 px: a pole with a glowing yellow lantern.'],
  ['Coins', 'trinket', 'rare', 'trinket/coins', 'trinket/coins', { main: 'p12', accent: 'p13' }, { main: 'p12', accent: 'p13' },
    'A stack of four gold coins and a bigger coin leaning on it with a rim and a gold S mark, two white sparkles. At 60 px: a gold stack with a round coin.']
];
const host = document.getElementById('items'), sheet = document.getElementById('sheet');
// the game-size sheet first: every item at 60 px, before above after, in one place
(function () {
  ITEMS.forEach(([name, slot, tier, bBase, aBase, bCols, aCols], k) => {
    const col = document.createElement('div'); col.className = 'sc';
    const wi = pickWearer([aCols.main, aCols.accent], k % 6), b = gameSize(() => buildBase(before, bBase, bCols), tier, wi), a = gameSize(() => buildBase(kit, aBase, aCols), tier, wi);
    col.append(b, a); col.insertAdjacentHTML('beforeend', '<i>' + name + '</i>'); sheet.appendChild(col);
  });
})();
function tile(label, cv, cls) { const d = document.createElement('div'); d.className = 'tile ' + (cls || ''); d.appendChild(cv); const c = document.createElement('i'); c.textContent = label; d.appendChild(c); return d; }
function colHead(t) { const h = document.createElement('div'); h.className = 'colhead'; h.textContent = t; return h; }
let n = -1;
const only = new URLSearchParams(location.search).get('i'), pick = only ? only.split(',').map(Number) : null;   // ?i=3,4 draws just those items
for (const [name, slot, tier, bBase, aBase, bCols, aCols, brief] of ITEMS) {
  n++; if (pick && !pick.includes(n)) continue;
  const i = pickWearer([aCols.main, aCols.accent], n % 6), hid = HOUSE_IDS[n % HOUSE_IDS.length];
  const bBuild = () => buildBase(before, bBase, bCols), aBuild = () => buildBase(kit, aBase, aCols);
  const card = document.createElement('section'); card.className = 'item';
  card.innerHTML = '<h3>' + name + '<span class="tier ' + tier + '">' + tier + '</span><small>' + slot + ' · before ' + bBase + ' · after ' + aBase + '</small></h3><p>' + brief + '</p>';
  const grid = document.createElement('div'); grid.className = 'cols'; card.appendChild(grid);
  const cols = [['Before', bBuild, { legacy: true }], ['After', aBuild, {}]];
  const colEls = cols.map(([t]) => { const c = document.createElement('div'); c.className = 'col'; c.appendChild(colHead(t)); grid.appendChild(c); return c; });
  const ref = document.createElement('div'); ref.className = 'col ref'; ref.appendChild(colHead('House model (V1)')); grid.appendChild(ref);
  cols.forEach(([t, build, o], k) => {
    const el = colEls[k];
    el.appendChild(tile('60 px', gameSize(build, tier, i), 'px60'));
    el.appendChild(tile('300 px, worn', worn(slot, build, tier, i, 300, o.legacy ? OLD_CAM : undefined)));
    el.appendChild(tile('on the floor', floor(build, tier, 300, o)));
  });
  ref.appendChild(tile('60 px', house(hid, 60), 'px60'));
  ref.appendChild(tile('300 px', house(hid, 300)));
  ref.appendChild(tile('on the floor', houseFloor(hid, tier)));
  host.appendChild(card);
}

document.getElementById('summary').textContent = ITEMS.length + ' items · before / after / house model · 60 px, 300 px worn, on the floor · console errors: ' + errors.length;
window.__CMP = { items: ITEMS.length, errors, ok: ITEMS.length === 28 && errors.length === 0 }; window.__CMP_DONE = true;
