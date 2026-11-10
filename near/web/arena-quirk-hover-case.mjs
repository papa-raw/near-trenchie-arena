import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { ROSTER } from './art/roster.js';
import { shortName } from './arena/names.mjs';
import { Hud } from './arena/hud.mjs';
class Element {
  constructor() { this.children = []; this.style = {}; this.className = ''; this.attributes = {}; this.textContent = ''; }
  appendChild(el) { this.children.push(el); return el; }
  querySelector(selector) { return this.children.find((c) => c.className === selector.slice(1)) || null; }
  setAttribute(k, v) { this.attributes[k] = v; }
  remove() {}
}
globalThis.document.createElement = () => new Element();
const rules = JSON.parse(await readFile(new URL('../arena/rules/integer-11.json', import.meta.url), 'utf8'));
const hud = Object.create(Hud.prototype);
Object.assign(hud, { w: 1440, h: 900, tags: new Map(), styles: new Map([['visitor', 'hunter']]), bounties: new Set(), KITS: { roster: [] },
  details: { rules }, tagLayer: new Element(), toScreen: () => ({ x: 400, y: 400 }) });
const fighter = { status: 0, items: { trinket: 'leg-laser-eyes' } };
const positions = new Map([['visitor', { x: 0, z: 0, f: fighter, state: 'alive' }]]);
hud.placeTags(positions, null);
const el = hud.tags.get('visitor');
assert.equal(el.querySelector('.quirk-line')?.textContent, 'visitor · ' + rules.item_quirks['leg-laser-eyes'].text);
assert.ok(el.attributes['aria-label'].includes(rules.item_quirks['leg-laser-eyes'].text)); assert.equal(el.tabIndex, 0);
fighter.items.trinket = 'leg-hydra-halo'; hud.placeTags(positions, null);
assert.equal(el.querySelector('.quirk-line').textContent, 'visitor · ' + rules.item_quirks['leg-hydra-halo'].text);
fighter.items.trinket = 'st-roll'; hud.placeTags(positions, null); assert.equal(el.querySelector('.quirk-line').textContent, '');
const css = await readFile(new URL('./arena.html', import.meta.url), 'utf8');
assert.ok(css.includes('.atag:hover .quirk-line') && css.includes('.atag:focus .quirk-line'), 'quirk line follows hover and keyboard focus');
hud.KITS.roster = ROSTER; hud.tags.clear();
const houses = new Map(ROSTER.map((row, i) => [row.trenchieId, { x: 100 + i * 40, z: 300, state: 'bench', f: { status: 1, items: row.kit } }]));
hud.placeTags(houses, null);
for (const row of ROSTER) assert.ok(hud.tags.get(row.trenchieId).querySelector('.quirk-line').textContent.startsWith(shortName(ROSTER, row.trenchieId) + ' · '), row.trenchieId + ' carries its short name');
process.stdout.write(JSON.stringify({ ok: true, hoverText: true, itemChange: true, focus: true, namedHouseTags: ROSTER.length }) + '\n');
