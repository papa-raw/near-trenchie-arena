// The real floor-sign HUD: automatic labels last 3 s, fade for 300 ms, then remove the complete announcement.
// Run only this regression: node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-legend-fade-case.mjs
import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { Hud } from './arena/hud.mjs';

let now = 1000;
Object.defineProperty(performance, 'now', { value: () => now, configurable: true });
class Element {
  constructor() {
    this.style = {}; this.dataset = {}; this.children = []; this.events = {}; this.parentNode = null;
    const classes = this.classes = new Set();
    this.classList = {
      contains: (c) => classes.has(c), add: (...cs) => cs.forEach((c) => classes.add(c)),
      remove: (...cs) => cs.forEach((c) => classes.delete(c)),
      toggle: (c, on = !classes.has(c)) => { if (on) classes.add(c); else classes.delete(c); },
    };
  }
  set className(v) { this.classes.clear(); v.split(/\s+/).filter(Boolean).forEach((c) => this.classes.add(c)); }
  get offsetWidth() { return this.classList.contains('short') && !this.classList.contains('open') ? 35 : this.classList.contains('nameonly') ? 120 : 190; }
  get offsetHeight() { return 35; }
  appendChild(el) { el.remove(); this.children.push(el); el.parentNode = this; return el; }
  append(...els) { els.forEach((el) => this.appendChild(el)); }
  setAttribute() {}
  addEventListener(type, fn) { this.events[type] = fn; }
  fire(type, e = {}) { this.events[type]?.({ stopPropagation() {}, ...e }); }
  remove() { if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; }
}
globalThis.document = { createElement: () => new Element(), createTextNode: () => new Element() };
const drop = (key, x = 2000) => ({ key, item: 'leg-test', x, y: 5000 });
const nameWalls = [{ x: 0, y: 0, w: 390, h: 400 }, { x: 0, y: 600, w: 390, h: 244 }, { x: 0, y: 400, w: 145, h: 200 }, { x: 255, y: 400, w: 135, h: 200 }];
const pictureWalls = [{ x: 0, y: 0, w: 390, h: 455 }, { x: 0, y: 545, w: 390, h: 299 }, { x: 0, y: 455, w: 170, h: 90 }, { x: 230, y: 455, w: 160, h: 90 }];
function hud(walls = []) {
  const h = Object.create(Hud.prototype);
  return Object.assign(h, {
    w: 390, h: 844, legends: new Map(), legLayer: new Element(), tagRects: walls, rects: {},
    ITEMS: { 'leg-test': { name: 'Test Crown', tier: 'legendary' } }, itemRenderer: null,
    toScreen: (x, y, z) => ({ x: x * 100, y: z * 100 - y * 33 }),
    lives: { get: () => ({ life: 2, level: 1 }) }, feed: { push() {} }, prejump: { start: () => false }, tagOf: () => 'Pebble',
    corner: { setSound() {} }, layoutHud() {}, placeStatus() {},
  });
}
function draw(h, drops, t) { now = t; h.syncDrops(drops, now); h.placeLegends(new Map(), now); }
const expanded = (lg) => lg.sign.parentNode && lg.sign.style.visibility !== 'hidden' && Number(lg.sign.style.opacity) > 0 && (!lg.sign.classList.contains('short') || lg.sign.classList.contains('open'));
const removed = (lg) => !lg.sign.parentNode && !lg.pin.parentNode;
let scenarios = 0;

// Every placement form, repeated snapshots/events/renders, an overlapping second drop and a respawn.
for (const [form, walls, x] of [['full', [], 2000], ['name', nameWalls, 2000], ['picture', pictureWalls, 2000], ['hidden', [], -1000]]) {
  const h = hud(walls), a = drop('a', x), b = drop('b', 3200);
  draw(h, [a], 1000); const lg = h.legends.get('a');
  assert.equal(form === 'hidden' ? lg.sign.style.visibility : lg.sign.dataset.form, form);
  draw(h, [a, b], 2000); h.onLegendDrop(a); // repeated announcement must not restart the first label
  draw(h, [a, b], 3999);
  if (form === 'full' || form === 'name') assert.ok(expanded(lg), form + ': visible for the full 3 s');
  draw(h, [a, b], 4150);
  if (form === 'full' || form === 'name') assert.equal(Number(lg.sign.style.opacity), 0.5, form + ': halfway through the fixed fade');
  draw(h, [a, b], 4300);
  assert.ok(!expanded(lg), form + ': first label gone by 3300 ms even while the item remains');
  assert.ok(h.legends.get('b').sign.parentNode, 'a second drop has its own lifetime');
  h.onRespawn({ fighter: 'pebble', life_id: 2 }, now);
  draw(h, [a, b], 10000);
  assert.ok(!expanded(lg) && !expanded(h.legends.get('b')), form + ': rerender/respawn cannot rearm expired labels');
  assert.ok(!lg.pin.parentNode, 'the announcement pin leaves with the label');
  if (form === 'hidden') { lg.x = 2; h.placeLegends(new Map(), now); }
  assert.ok(removed(lg), form + ': no picture card or pin returns on screen');
  draw(h, [], 11000); h.placeLegends(new Map(), 11300);
  assert.equal(h.legends.size, 0, 'grabbed/expired floor items release their signs and pins');
  assert.equal(h.legLayer.children.length, 0);
  scenarios++;
}

// No render while hidden: elapsed wall time counts. An idle/reconnecting HUD expires labels too.
for (const idle of [false, true]) {
  const h = hud(), a = drop('gap'); draw(h, [a], 20000); const lg = h.legends.get('gap');
  now = 80000;
  if (idle) h.idle(now); else draw(h, [a], now);
  assert.ok(!expanded(lg) && removed(lg), (idle ? 'idle' : 'hidden-tab resume') + ': no stale automatic label');
  scenarios++;
}

// Opening a collision preview is limited to the announcement's deadline; detached handlers cannot rearm it.
{
  const h = hud(pictureWalls), a = drop('interactive'); draw(h, [a], 100000); const lg = h.legends.get(a.key);
  lg.sign.fire('pointerenter', { pointerType: 'touch' }); h.placeLegends(new Map(), now);
  assert.ok(!lg.sign.classList.contains('open'), 'touch passing over does not open the preview');
  lg.sign.fire('click'); h.placeLegends(new Map(), now); assert.ok(expanded(lg), 'a deliberate tap opens the active label');
  draw(h, [a], 103150); assert.equal(Number(lg.sign.style.opacity), 0.5, 'tap cannot postpone the automatic fade');
  draw(h, [a], 103300); assert.ok(removed(lg), 'tap leaves no compact card after the deadline');
  lg.sign.fire('pointerenter', { pointerType: 'mouse' }); draw(h, [a], 120000);
  assert.ok(removed(lg), 'detached hover cannot rearm an expired announcement');
  draw(h, [], 121000); h.placeLegends(new Map(), 121300);
  draw(h, [drop('fresh')], 122000); assert.ok(h.legends.get('fresh').sign.parentNode, 'a fresh drop still shows normally');
  scenarios++;
}
console.log('arena-legend-fade-case: ' + scenarios + ' lifetime scenarios OK');
