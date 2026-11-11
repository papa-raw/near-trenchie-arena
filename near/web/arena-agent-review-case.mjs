import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Hud } from './arena/hud.mjs';
import * as social from './arena/social.mjs';
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
  // the ticker is the live path for a spoken line: a blocked one shows the emote and says so, never the original
  const line = (row) => social.tickerParts({ type: 'say', row: { who: 'dev-pebble', ...row } }, []).parts.map((p) => p[0]).join(' ');
  assert.match(line({ text:'(o_o)', blocked:true, muted:false, label:null }), /blocked line/);
  assert.doesNotMatch(line({ text:'(o_o)', blocked:true, muted:false, label:null }), /fraud/);
  assert.match(line({ text:'(o_o)', blocked:true, muted:false, label:'autopilot' }), /blocked line · autopilot/);
} else if (mode === 'collision') {
  assert.equal(typeof social.placeSpeechPanel, 'function');
  const intersects = (a,b) => Math.min(a.x+a.w,b.x+b.w) > Math.max(a.x,b.x) && Math.min(a.y+a.h,b.y+b.h) > Math.max(a.y,b.y);
  for (const width of [390,1440]) {
    const anchor = { x: 150, y: 200, w: 90, h: 20 };
    const neighbours = [anchor, {x:140,y:222,w:100,h:25}, {x:142,y:152,w:100,h:35}];
    const box = social.placeSpeechPanel(anchor, {w:240,h:80}, neighbours, width, 844);
    assert.ok(box, 'a clear bubble position exists');
    assert.ok(neighbours.every((tag) => !intersects(box,tag)), 'speech never covers a tag');
    assert.ok(box.x>=8 && box.y>=8 && box.x+box.w<=width-8 && box.y+box.h<=836);
    // the live path: the speaker's emoji floats over its tag, placed by the same rule, never over another tag
    globalThis.document.createElement = () => { const el = new Element(); el.offsetWidth = 240; el.offsetHeight = 80; el.replaceChildren = (...c) => { el.children = c; }; return el; };
    const root = new Element(), tag = new Element(), view = new social.Social({ roster: [] }, root);
    view.latest.set('dev-pebble', { text: 'A calm shore.', emoji: '\u{1F5FF}', at: 0 });
    view.frame(new Map([['dev-pebble', { f: { status: 0 } }]]), { w: width, h: 844, rects: {}, tagRects: [{ ...anchor, id: 'dev-pebble' }, ...neighbours.slice(1)], tags: new Map([['dev-pebble', tag]]), cardRects: [] }, 0);
    const mark = view.marks.get('dev-pebble'); assert.ok(mark, 'the speaker gets its emoji');
    assert.equal(mark.parentNode, view.layer, 'the emoji never grows the already-placed tag');
    assert.equal(mark.attributes['data-fighter-id'], 'dev-pebble');
    assert.equal(tag.children.length, 0);
    const actual = {x:parseFloat(mark.style.left),y:parseFloat(mark.style.top),w:240,h:80};
    assert.ok(neighbours.every((rect) => !intersects(actual,rect)), 'the rendered emoji avoids every tag');
  }
} else throw new Error('Choose dataset, focus, name, blocked or collision');
process.stdout.write(JSON.stringify({ mode, ok: true })+'\n');
}
