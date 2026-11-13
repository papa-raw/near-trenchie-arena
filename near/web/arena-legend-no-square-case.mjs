// The floor item outlives its announcement: after 3 s + 300 ms no sign, compact card or pin remains in the DOM.
// node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-legend-no-square-case.mjs
import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { Hud } from './arena/hud.mjs';

let now = 1000;
Object.defineProperty(performance, 'now', { value: () => now, configurable: true });
class Element {
  constructor() {
    this.style = {}; this.dataset = {}; this.children = []; this.events = {}; this.parentNode = null;
    const classes = this.classes = new Set();
    this.classList = { contains: (c) => classes.has(c), add: (...cs) => cs.forEach((c) => classes.add(c)),
      remove: (...cs) => cs.forEach((c) => classes.delete(c)),
      toggle: (c, on = !classes.has(c)) => { if (on) classes.add(c); else classes.delete(c); } };
  }
  set className(value) { this.classes.clear(); value.split(/\s+/).filter(Boolean).forEach((c) => this.classes.add(c)); }
  get offsetWidth() { return this.classes.has('short') && !this.classes.has('open') ? 35 : this.classes.has('nameonly') ? 120 : 190; }
  get offsetHeight() { return 35; }
  appendChild(el) { el.remove(); this.children.push(el); el.parentNode = this; return el; }
  append(...els) { els.forEach((el) => this.appendChild(el)); }
  setAttribute() {}
  addEventListener(type, fn) { this.events[type] = fn; }
  fire(type, event = {}) { this.events[type]?.({ stopPropagation() {}, ...event }); }
  remove() { if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; }
}
globalThis.document = { createElement: () => new Element() };
const nameWalls = [{ x: 0, y: 0, w: 390, h: 400 }, { x: 0, y: 600, w: 390, h: 244 }, { x: 0, y: 400, w: 145, h: 200 }, { x: 255, y: 400, w: 135, h: 200 }];
const pictureWalls = [{ x: 0, y: 0, w: 390, h: 455 }, { x: 0, y: 545, w: 390, h: 299 }, { x: 0, y: 455, w: 170, h: 90 }, { x: 230, y: 455, w: 160, h: 90 }];
function hud(walls = []) {
  return Object.assign(Object.create(Hud.prototype), {
    w: 390, h: 844, legends: new Map(), legLayer: new Element(), tagRects: walls, rects: {},
    ITEMS: { crown: { name: 'Coral Crown', tier: 'legendary' } }, itemRenderer: null,
    toScreen: (x, y, z) => ({ x: x * 100, y: z * 100 - y * 33 }),
    lives: { get: () => ({ life: 2, level: 1 }) }, feed: { push() {} }, prejump: { start: () => false }, tagOf: () => 'Pebble',
    corner: { setSound() {} }, layoutHud() {}, placeStatus() {},
  });
}
const drop = (key, x = 2000) => Object.freeze({ key, item: 'crown', x, y: 5000 });
function draw(h, drops, time) { now = time; h.syncDrops(drops, now); h.placeLegends(new Map(), now); }
function gone(h, lg, label) {
  assert.equal(h.legLayer.children.length, 0, label + ': no overlay DOM, including picture card and pin');
  assert.equal(lg.sign.parentNode, null); assert.equal(lg.pin.parentNode, null);
  assert.deepEqual(h.legendRects, [], label + ': no invisible placement obstacles');
}
let scenarios = 0;
for (const [form, walls, x] of [['full', [], 2000], ['name', nameWalls, 2000], ['picture', pictureWalls, 2000], ['hidden', [], -1000]]) {
  const h = hud(walls), item = drop('one', x), drops = Object.freeze([item]);
  draw(h, drops, 1000); const lg = h.legends.get(item.key);
  assert.equal(form === 'hidden' ? lg.sign.style.visibility : lg.sign.dataset.form, form);
  draw(h, drops, 3999); h.onLegendDrop(item, now);
  assert.equal(h.legLayer.children.length, 2, 'the announcement still exists before its deadline');
  draw(h, drops, 4300); gone(h, lg, form);
  assert.equal(drops[0], item, 'the floor item remains untouched');
  assert.equal(h.legends.get(item.key), lg, 'the expired record prevents repeated snapshots rearming');
  h.onLegendDrop(item, 5000); h.resize(1440, 900); h.onRespawn({ fighter: 'pebble', life_id: 2 }, 5000);
  draw(h, drops, 5000); lg.x = 2; h.placeLegends(new Map(), 6000); gone(h, lg, 'repeat, resize, respawn and camera return');
  now = 80000; h.idle(now); gone(h, lg, 'idle and hidden-tab resume');
  draw(h, [], 81000); h.placeLegends(new Map(), 81300);
  assert.equal(h.legends.size, 0, 'departed items release expired records');
  scenarios++;
}
{
  const h = hud(), first = drop('first'), second = drop('second', 3200);
  draw(h, [first], 1000); const one = h.legends.get('first');
  draw(h, [first, second], 2000); const two = h.legends.get('second');
  draw(h, [first, second], 4300);
  assert.equal(one.sign.parentNode, null); assert.equal(one.pin.parentNode, null);
  assert.equal(h.legLayer.children.length, 2, 'a newer announcement keeps its own lifetime');
  draw(h, [first, second], 5150);
  assert.equal(Number(two.sign.style.opacity), 0.5); assert.equal(Number(two.pin.style.opacity), 0.5, 'the pin fades with the sign');
  draw(h, [first, second], 5300); gone(h, two, 'both deadlines elapsed');
  scenarios++;
}
for (const idle of [false, true]) {
  const h = hud(pictureWalls), item = drop('gap'); draw(h, [item], 20000); const lg = h.legends.get(item.key);
  now = 80000; if (idle) h.idle(now); else draw(h, [item], now);
  gone(h, lg, idle ? 'idle without a new snapshot' : 'first frame after a gap'); scenarios++;
}
{
  const h = hud(pictureWalls), item = drop('tap'); draw(h, [item], 100000); const lg = h.legends.get(item.key);
  now = 102900; lg.sign.fire('click'); lg.sign.fire('pointerenter', { pointerType: 'mouse' });
  draw(h, [item], 103150); assert.equal(Number(lg.sign.style.opacity), 0.5, 'opening a collision preview does not extend its fade');
  draw(h, [item], 103300); gone(h, lg, 'tap and hover do not leave a permanent overlay');
  lg.sign.fire('click'); lg.sign.fire('pointerenter', { pointerType: 'mouse' }); draw(h, [item], 104000); gone(h, lg, 'detached handlers cannot rearm');
  scenarios++;
}
process.stdout.write('arena-legend-no-square-case: ' + scenarios + ' scenarios; zero overlay nodes after 3.3 s, floor items untouched\n');
