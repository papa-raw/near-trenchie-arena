// kit.js — draws every menu row worn and on the floor with its tier glow, the extra kit shapes, and the 60 px strips.
import { buildBase, buildSpec } from './kit3d.js';
import { errors, worn, floor, gameSize, pickWearer } from './kitview.js';

const kit = await (await fetch('../../items/kit.json')).json();
function card(host, name, tierName, note, a, b) {
  const d = document.createElement('div'); d.className = 'card';
  const p = document.createElement('div'); p.className = 'pair'; p.append(a, b); d.appendChild(p);
  d.insertAdjacentHTML('beforeend', '<b>' + name + '<span class="tier ' + tierName + '">' + tierName + '</span></b><small>' + note + '</small>'); host.appendChild(d);
}

let drawn = 0;
const strips = document.getElementById('strips'), stripRows = {};
for (const slot of ['head', 'body', 'weapon', 'trinket']) {
  const box = document.createElement('div'); box.className = 'strip'; box.innerHTML = '<div class="row"></div><div class="cap">' + slot + '</div>'; strips.appendChild(box); stripRows[slot] = box.querySelector('.row');
}
const menu = document.getElementById('g-menu'), used = new Set();
let i = 0;
for (const row of kit.menu) {
  const spec = await (await fetch('../../items/' + kit.spec_dir + '/' + row.row + '.json')).json(), slot = spec.slot, build = () => buildSpec(kit, spec);
  used.add(spec.kit);
  const w = pickWearer([spec.colors.main, spec.colors.accent], i);
  card(menu, spec.name, spec.tier, row.row + ' · ' + spec.kit + ' · ' + Object.values(spec.colors).join(' '), worn(slot, build, spec.tier, w), floor(build, spec.tier));
  stripRows[slot].appendChild(gameSize(build, spec.tier, w)); i++; drawn++;
}
const extra = document.getElementById('g-extra');
for (const slot of ['head', 'body', 'weapon', 'trinket']) {
  for (const [id, b] of Object.entries(kit.bases[slot])) {
    if (used.has(slot + '/' + id)) continue;
    const build = () => buildBase(kit, slot + '/' + id);
    const w = pickWearer([b.colors.main, b.colors.accent], i);
    card(extra, b.name, 'rare', slot + '/' + id + ' · ' + b.nodes.length + ' nodes', worn(slot, build, 'rare', w), floor(build, 'rare'));
    stripRows[slot].appendChild(gameSize(build, 'rare', w)); i++; drawn++;
  }
}
const ok = drawn >= 32 && errors.length === 0;
document.getElementById('summary').textContent = drawn + ' items drawn worn and on the floor · ' + Object.values(kit.bases).reduce((n, b) => n + Object.keys(b).length, 0) + ' shapes · console errors: ' + errors.length + ' · ' + kit.spec;
window.__KIT = { drawn, menu: kit.menu.length, errors, ok }; window.__KIT_DONE = true;
