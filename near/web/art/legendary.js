// legendary.js — the 14 legendaries: the house trenchie wearing it at 60 px and 300 px, the item on the floor in gold glow, the emblem on its plate.
import * as THREE from 'three';
import { LOOK3, makeHouse } from './index.js';
import { buildSpec, wear } from './kit3d.js';
import { errors, view, floor } from './kitview.js';

const kit = await (await fetch('../../items/kit.json')).json();
const lore = await (await fetch('../../lore/kits.json')).json();
const host = document.getElementById('items'), sheet = document.getElementById('sheet');
function tile(label, cv, cls) { const d = document.createElement('div'); d.className = 'tile ' + (cls || ''); d.appendChild(cv); const c = document.createElement('i'); c.textContent = label; d.appendChild(c); return d; }
function wornOn(id, spec, size) {
  const w = makeHouse(id); w.object3d.rotation.y = -0.38; w.joints.mountTrinket.clear();
  wear(w, buildSpec(kit, spec), 'legendary');
  const cv = size === 60 ? view(w.object3d, 60, [0, 0.36, 0], 0.54, 30, 28) : view(w.object3d, size, [0.05, 0.36, 0.05], 0.4, 52, 14);
  w.dispose(); return cv;
}
function emblem(spec) {
  const holder = new THREE.Group(), plate = LOOK3.kit.M(new THREE.CylinderGeometry(0.092, 0.092, 0.012, 40), 'p13', {});
  plate.rotation.x = Math.PI / 2; plate.position.z = 0.004;
  const g = buildSpec(kit, spec); g.position.y = -0.08; holder.add(plate, g);
  return view(holder, 300, [0, 0, 0.02], 0.115, 14, 10);
}
let n = 0, nodes = 0, idx = -1;
const only = new URLSearchParams(location.search).get('i'), pick = only ? only.split(',').map(Number) : null;   // ?i=3,13 draws just those cards
for (const t of lore.trenchies) {
  idx++;
  const lid = t.legendary.id, spec = await (await fetch('../../items/' + kit.spec_dir + '/' + lid + '.json')).json();
  const col = document.createElement('div'); col.className = 'sc';
  col.append(wornOn(t.trenchieId, spec, 60), floor(() => buildSpec(kit, spec), 'legendary', 60)); col.insertAdjacentHTML('beforeend', '<i>' + spec.name + '</i>'); sheet.appendChild(col);
  if (pick && !pick.includes(idx)) { n++; nodes += spec.nodes.length; continue; }
  const card = document.createElement('section'); card.className = 'item';
  card.innerHTML = '<h3>' + spec.name + '<span class="tier legendary">legendary</span><small>' + t.name + ' · ' + lid + ' · ' + spec.sig + ' · ' + spec.nodes.length + ' nodes</small></h3><p>' + t.legendary.look + '</p>';
  const grid = document.createElement('div'); grid.className = 'cols'; card.appendChild(grid);
  const c1 = document.createElement('div'); c1.className = 'col'; c1.appendChild(tile('60 px, worn by ' + t.name, wornOn(t.trenchieId, spec, 60), 'px60')); c1.appendChild(tile('300 px, worn', wornOn(t.trenchieId, spec, 300)));
  const c2 = document.createElement('div'); c2.className = 'col'; c2.appendChild(tile('on the floor', floor(() => buildSpec(kit, spec), 'legendary', 300)));
  const c3 = document.createElement('div'); c3.className = 'col'; c3.appendChild(tile('the emblem on its plate', emblem(spec)));
  grid.append(c1, c2, c3); host.appendChild(card); n++; nodes += spec.nodes.length;
}
document.getElementById('summary').textContent = n + ' legendaries · ' + nodes + ' nodes · console errors: ' + errors.length + ' · ' + kit.item_spec;
window.__LEG = { n, nodes, errors, ok: n === 14 && errors.length === 0 }; window.__LEG_DONE = true;
