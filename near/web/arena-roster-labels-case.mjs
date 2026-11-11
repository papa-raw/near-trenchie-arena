// Roster node case: the card labels come from the host's public roster projection (counts, meter, chip).
// Run: node near/web/arena-roster-labels-case.mjs   (no browser; the browser count check is arena-roster-count-case.mjs)
import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { register } from 'node:module';
import { RosterFeed, rosterLabels, rosterUrl } from './arena/roster.mjs';
register('./arena-view-remainder-loader.mjs', import.meta.url);     // the browser import map's 'three', for hud.mjs
const { Hud } = await import('./arena/hud.mjs');

const roster = { admitted: 4, chip: null, house_spend_today_microusd: 12345, members: [
  { id: 'satrenchi', persona: 'Satrenchi', house: true, state: 'in the ring', model: 'm', spend_today_microusd: 1 },
  { id: 'avichad', persona: 'Avichad', house: true, state: 'on the bench', model: 'm', spend_today_microusd: 2 },
  { id: 'laser-sailor', persona: 'Laser Sailor', house: true, state: 'in the ring', model: 'm', spend_today_microusd: 3 },
  { id: 'dev-pat', persona: 'DEV pat', house: false, state: 'in the ring', model: 'dev' }] };

assert.equal(rosterUrl('ws://127.0.0.1:8765'), 'http://127.0.0.1:8765/house/roster');
assert.equal(rosterUrl('wss://arena.example/ws?x=1'), 'https://arena.example/house/roster');
let l = rosterLabels(roster);
assert.equal(l.house, 'House'); assert.equal(l.houseDetail, '3 admitted · $0.012 today');
assert.equal(l.players, 'Players', 'the Players card keeps its approved label');
assert.deepEqual([...l.houseIds].sort(), ['avichad', 'laser-sailor', 'satrenchi']);
assert.equal(rosterLabels(roster, true).houseDetail, '3 admitted', 'narrow drops the meter, never the count');
assert.equal(rosterLabels({ ...roster, chip: 'autopilot' }, true).houseDetail, '3 admitted · autopilot', 'the chip always shows');
assert.equal(rosterLabels({ ...roster, battle_style: 'lean' }).houseDetail, '3 admitted · $0.012 today · lean', 'the house’s battle style shows');
assert.equal(rosterLabels({ ...roster, battle_style: 'full' }, true).houseDetail, '3 admitted · full');

// the HUD's cards take their labels and their house split from the projection
class Node {
  constructor() { this.children = []; this.style = { cssText: '' }; this.dataset = {}; this.className = ''; this.textContent = ''; this.parentNode = null; }
  appendChild(n) { this.children.push(n); n.parentNode = this; return n; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((c) => c !== this); }
}
globalThis.document.createElement = () => new Node();
globalThis.document.body = new Node();
const hud = Object.create(Hud.prototype);
Object.assign(hud, { w: 1440, h: 900, cards: [], cardLayer: new Node(), applyBanner() {}, roster,
  artCache: { mount: async () => ({ rects: [{ id: 'board', x: 0, y: 0, w: 200, h: 80 }] }), panel: () => new Node() }, tagOf: (id) => id });
await hud.buildCards(['dev-pat'], new Map(), 5, { x: 10, y: 10, w: 200, h: 80 });
const labels = hud.cardLayer.children.filter((n) => n.dataset.card).map((n) => [n.dataset.card, n.textContent]);
assert.deepEqual(labels, [['house', 'House'], ['house-roster', '3 admitted · $0.012 today'], ['players', 'Players · since you arrived']]);
// With no player seated the House card is the last one: the caption stays the board's, the roster its own tag
await hud.buildCards([], new Map(), 5, { x: 10, y: 10, w: 200, h: 80 });
const alone = hud.cardLayer.children.filter((n) => n.dataset.card).map((n) => [n.dataset.card, n.textContent]);
assert.deepEqual(alone, [['house', 'House · since you arrived'], ['house-roster', '3 admitted · $0.012 today']]);

// a failed poll keeps the last roster
const got = []; let fail = false;
const feed = new RosterFeed('http://x/house/roster', (r) => got.push(r), { fetchFn: async () => { if (fail) throw new Error('down'); return { ok: true, json: async () => roster }; } });
const warn = console.warn; console.warn = () => {};
await feed.poll(); fail = true; await feed.poll(); console.warn = warn;
assert.equal(got.length, 1);

// The DEFAULT fetch, shaped like a browser's (it throws "Illegal invocation" unless called on the global)
const pageFetch = async function (url) {
  if (this !== undefined && this !== globalThis) throw new TypeError("Failed to execute 'fetch' on 'Window': Illegal invocation");
  return { ok: true, json: async () => roster };
};
const realFetch = globalThis.fetch; globalThis.fetch = pageFetch;
const plain = []; const warned = []; console.warn = (...a) => warned.push(a.join(' '));
await new RosterFeed('http://x/house/roster', (r) => plain.push(r)).poll();
console.warn = warn; globalThis.fetch = realFetch;
assert.deepEqual(warned, [], 'the default fetch polls without error: ' + warned.join(' | '));
assert.equal(plain.length, 1, 'the labels arrive through the default fetch');
process.stdout.write(JSON.stringify({ ok: true, labels }) + '\n');
