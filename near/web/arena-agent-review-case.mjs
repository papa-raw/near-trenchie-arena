import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Hud } from './arena/hud.mjs';
import * as social from './arena/social.mjs';
import * as feed from './arena/feed.mjs';
const modes = process.argv[2] ? [process.argv[2]] : ['dataset', 'focus', 'name', 'blocked', 'collision'];
class Element {
  constructor() { this.children = []; this.style = {}; this.dataset = {}; this.className = ''; this.attributes = {}; this.textContent = ''; this.offsetWidth = 90; this.offsetHeight = 20; }
  appendChild(el) { this.children.push(el); el.parentNode = this; return el; }
  querySelector(selector) { return this.children.find((c) => c.className === selector.slice(1)) || null; }
  setAttribute(k, v) { this.attributes[k] = v; }
  remove() {}
}
function hudFixture() {
  globalThis.document.createElement = () => new Element();
  const hud = Object.create(Hud.prototype);
  Object.assign(hud, { w: 390, h: 844, tags: new Map(), styles: new Map(), bounties: new Set(), KITS: { roster: [], players: [{ trenchieId: 'dev-pebble', name: 'Pebble Skipper', tag: 'Pebble', nameNotice: 'guard list missing · name unchecked' }] }, tagLayer: new Element(), toScreen: () => ({ x: 180, y: 200 }) });
  const pos = new Map([['dev-pebble', { x: 0, z: 0, state: 'alive', f: { status: 0, target: 'neighbour', items: {} } }], ['neighbour', { x: 1, z: 1, state: 'alive', f: { status: 0, items: {} } }]]);
  hud.placeTags(pos, null); return hud;
}
for (const mode of modes) {
if (mode === 'dataset') {
  const hud = hudFixture(); assert.equal(hud.tags.get('dev-pebble').attributes['data-fighter-id'], 'dev-pebble');
} else if (mode === 'focus') {
  const css = await readFile(new URL('./arena.html', import.meta.url), 'utf8');
  assert.match(css, /\.atag \.focus-mark\s*\{[^}]*display:\s*block/);
  const hud = hudFixture(); assert.match(hud.tags.get('dev-pebble').querySelector('.focus-mark')?.textContent || '', /neighbour/);
  assert.match(hud.tags.get('neighbour').className, /focus-target/);
} else if (mode === 'name') {
  const hud = hudFixture(); assert.match(hud.tags.get('dev-pebble').querySelector('.name-notice')?.textContent || '', /name unchecked/);
} else if (mode === 'blocked') {
  // the merged feed is the live path for a spoken line: a blocked one shows the emote and says so, never the original
  const line = (row) => { const sl = feed.slip(social.sayItem({ id: 1, who: 'dev-pebble', ...row }), (id) => id); return sl.parts.map((p) => p.text).join(''); };
  assert.match(line({ text:'(o_o)', blocked:true, muted:false, label:null }), /blocked line/);
  assert.doesNotMatch(line({ text:'(o_o)', blocked:true, muted:false, label:null }), /fraud/);
  assert.match(line({ text:'(o_o)', blocked:true, muted:false, label:'autopilot' }), /blocked line · autopilot/);
} else if (mode === 'collision') {
  // Q4 (Pat): no emoji over a head, so no speech mark can cover a tag; the emoji rides in the feed line beside the name
  assert.equal(social.placeSpeechPanel, undefined); assert.equal(social.SAY_EMOJI_MS, undefined);
  const said = []; const view = new social.Social({ roster: [] }, { onSay: (item) => said.push(item) });
  view.apply({ version: 1, players: [], feed: [{ id: 7, who: 'dev-pebble', text: 'A calm shore.', emoji: '\u{1F5FF}' }] });
  const sl = feed.slip(said[0], (id) => id);
  assert.deepEqual([sl.who, sl.emoji, sl.parts[0].text], ['dev-pebble', '\u{1F5FF}', '“A calm shore.”']);
} else throw new Error('Choose dataset, focus, name, blocked or collision');
process.stdout.write(JSON.stringify({ mode, ok: true })+'\n');
}
