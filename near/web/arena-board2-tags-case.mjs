// The arena HUD's crowd card on the real Hud.placeTags (approved board 2): three fighters within reach share one card
// and their own tags hide; when the crowd breaks up, each fighter's own tag is back on the very next frame (no blink).
//   node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-board2-tags-case.mjs
import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { Hud } from './arena/hud.mjs';
import { Lives } from './arena/lives.mjs';

class Element {
  constructor() { this.children = []; this.style = {}; this.dataset = {}; this.className = ''; this.attributes = {}; this.textContent = ''; this.offsetWidth = 80; this.offsetHeight = 18; }
  appendChild(el) { this.children.push(el); el.parentNode = this; return el; }
  append(...els) { for (const el of els) this.appendChild(el); }
  replaceChildren(...els) { this.children = []; this.append(...els); }
  querySelector(selector) { return this.children.find((c) => c.className === selector.slice(1)) || null; }
  setAttribute(k, v) { this.attributes[k] = v; }
  remove() { this.removed = true; }
}
globalThis.document.createElement = () => new Element();

const at = new Map([['a', { x: 600, y: 400 }], ['b', { x: 660, y: 410 }], ['c', { x: 720, y: 400 }], ['d', { x: 200, y: 700 }]]);   // d stands alone
const hud = Object.create(Hud.prototype);
Object.assign(hud, { w: 1440, h: 900, tags: new Map(), styles: new Map(), bounties: new Set(), KITS: { roster: [], players: [] }, tagLayer: new Element(),
  lives: new Lives(), toScreen: (x, y, z) => ({ x, y: z }) });
const pos = () => new Map([...at].map(([id, p]) => [id, { x: p.x, z: p.y, state: 'alive', f: { status: 0, items: {} } }]));

hud.placeTags(pos(), null, 0);
assert.equal(hud.cards.size, 1, 'three within reach share one card');
const card = [...hud.cards.values()][0].el;
assert.equal(card.children[0].textContent, '3 here');
assert.deepEqual(card.children.slice(1).map((r) => r.dataset.fighterId), ['a', 'b', 'c'], 'listed left to right');
for (const id of ['a', 'b', 'c']) assert.match(hud.tags.get(id).className, /tag-hidden/, id + ' hides its own tag while in the card');

at.set('c', { x: 1100, y: 700 }); at.set('a', { x: 300, y: 300 });   // the crowd breaks up
hud.placeTags(pos(), null, 50);
assert.equal(hud.cards.size, 0, 'the card goes with the crowd');
for (const id of ['a', 'b', 'c', 'd']) assert.doesNotMatch(hud.tags.get(id).className, /tag-hidden/, id + ' shows its own tag on the next frame');
// the page's status pill ("No arena at … retrying") stands clear of the corner buttons and the feed, not on top of them
const status = { classList: { contains: (c) => c === 'warn' }, offsetWidth: 190, offsetHeight: 60, style: {} };
Object.assign(hud, { statusEl: status, w: 390, h: 844, rects: { btn0: { x: 159, y: 788, w: 81, h: 44 }, btn1: { x: 250, y: 788, w: 132, h: 44 }, feed: { x: 8, y: 620, w: 374, h: 150 } } });
hud.placeStatus();
const top = parseFloat(status.style.top);
assert.ok(top + 60 <= 788 - 4 && top + 60 <= 620, 'the status pill sits above the buttons and the feed: top ' + top);
console.log('arena-board2-tags-case: OK');
