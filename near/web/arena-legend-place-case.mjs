// The legendary floor signs under the phone camera (board 2's sign, board 3's 2.8x zoom): each sign keeps its pin on the
// item and takes a clear spot, so no sign covers another sign's text, a body, a tag or the fixed HUD, and none leaves the
// screen; the words stay wherever they fit: the full sign, else the picture and the name, else the picture alone (a
// tap or hover opens the full sign); never a cut word. The pure placement
// (legend-place.mjs) and the real Hud.placeLegends on stub elements.
//   node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-legend-place-case.mjs
import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { placeLegendSigns, bodyBox, MARGIN, LIFT, GAP } from './arena/legend-place.mjs';
import { Hud } from './arena/hud.mjs';

let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };
const hit = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
const onScreen = (r, v) => r.x >= MARGIN - 0.01 && r.y >= MARGIN - 0.01 && r.x + r.w <= v.w - MARGIN + 0.01 && r.y + r.h <= v.h - MARGIN + 0.01;
function clean(out, obstacles, view, label) {
  const rs = [...out.values()].filter((p) => !p.hidden);
  for (let i = 0; i < rs.length; i++) {
    ok(onScreen(rs[i], view), label + ': sign ' + i + ' on screen');
    ok(!obstacles.some((o) => hit(rs[i], o)), label + ': sign ' + i + ' covers no body, tag or panel');
    for (let j = i + 1; j < rs.length; j++) ok(!hit(rs[i], rs[j]), label + ': signs ' + i + ' and ' + j + ' apart');
  }
}
const PHONE = { w: 390, h: 844 };
// every shown sign sits right next to its pin (no line joins them; Pat's item 35): its nearest edge within the default
// lift of the pin, or the picture on the pin itself; and no shown sign covers another sign's pin
function nextToPins(out, signs, label) {
  for (const [k, p] of out) {
    if (p.hidden) continue;
    const s = signs.find((g) => g.key === k), nx = Math.max(p.x, Math.min(s.ax, p.x + p.w)), ny = Math.max(p.y, Math.min(s.ay, p.y + p.h));
    ok(Math.hypot(nx - s.ax, ny - s.ay) <= Math.hypot(GAP, LIFT) + 0.01, label + ': sign ' + k + ' right next to its pin (' + p.pos + ')');
    for (const o of signs) if (o.key !== k) ok(!hit(p, { x: o.ax - 5, y: o.ay - 5, w: 10, h: 10 }), label + ': sign ' + k + ' clear of pin ' + o.key);
  }
}
const sign = (key, ax, ay) => ({ key, ax, ay, w: 190, h: 35, nw: 120, nh: 35, cw: 35, ch: 35 });   // "LEGENDARY: LASER EYES" at 11px; "LASER EYES"; the picture 26 + padding

// 1. one sign, open floor: the full form above its pin
{
  const out = placeLegendSigns([sign('a', 200, 500)], [], PHONE), p = out.get('a');
  ok(p.pos === 'up' && p.form === 'full' && !p.hidden, 'alone: full, above the pin');
  ok(Math.abs(p.x + p.w / 2 - 200) < 0.01 && p.y + p.h <= 500, 'alone: centred over its pin');
}

// 2. a phone sample from review: two drops 20 px apart with bodies beside them (the old placement put one sign over the other)
{
  const bodies = [bodyBox({ x: 150, y: 520 }, { x: 150, y: 470 }), bodyBox({ x: 260, y: 515 }, { x: 260, y: 465 })];   // a body ~50 px tall at 2.8x (measured live)
  const tags = [{ x: 120, y: 440, w: 70, h: 18 }, { x: 230, y: 435, w: 70, h: 18 }];
  const signs = [sign('a', 195, 500), sign('b', 215, 505)], obstacles = [...bodies, ...tags];
  const out = placeLegendSigns(signs, obstacles, PHONE);
  clean(out, obstacles, PHONE, 'two drops'); nextToPins(out, signs, 'two drops');
  ok([...out.values()].filter((p) => !p.hidden).length >= 1 && [...out.values()].every((p) => !p.hidden || p.hidden === 'no room'), 'two drops: one sign shown; one with no room next to its pin keeps only its pin');
  ok(JSON.stringify([...placeLegendSigns([...signs].reverse(), obstacles, PHONE)]) === JSON.stringify([...out]), 'same drops, same spots (order-free: no flicker frame to frame)');
}

// 3. a crowd at 2.8x: four drops among six bodies at the screen's middle
{
  const bodies = [[120, 470], [170, 480], [220, 470], [270, 485], [150, 560], [240, 565]].map(([x, y]) => bodyBox({ x, y }, { x, y: y - 50 }));
  const signs = [sign('a', 145, 500), sign('b', 200, 505), sign('c', 250, 510), sign('d', 195, 590)];
  const out = placeLegendSigns(signs, bodies, PHONE);
  clean(out, bodies, PHONE, 'crowd'); nextToPins(out, signs, 'crowd');
  ok([...out.values()].some((p) => !p.hidden), 'crowd: a sign with room shows');
}

// 3c. the same two drops on open floor: both show, right next to their pins, apart
{
  const signs = [sign('a', 195, 500), sign('b', 215, 505)], out = placeLegendSigns(signs, [], PHONE);
  clean(out, [], PHONE, 'open floor'); nextToPins(out, signs, 'open floor');
  ok([...out.values()].every((p) => !p.hidden), 'open floor: both shown');
}

// 3a. no sign sits on a pin (the live run: a red pin dot on "LEGENDARY: STACK SATS"); only the picture form may take its
// own pin's place (3d)
{
  const signs = [sign('a', 200, 500), sign('b', 220, 470), sign('c', 150, 440)], out = placeLegendSigns(signs, [], PHONE);
  for (const [k, p] of out) for (const s of signs) ok(!hit(p, { x: s.ax - 5, y: s.ay - 5, w: 10, h: 10 }), 'pins: sign ' + k + ' clear of pin ' + s.key);
}

// 3b. a busier crowd: every shown sign right next to its pin
{
  const bodies = [[120, 470], [170, 480], [220, 470], [270, 485], [150, 560], [240, 565]].map(([x, y]) => bodyBox({ x, y }, { x, y: y - 50 }));
  const signs = [sign('a', 145, 500), sign('b', 200, 505), sign('c', 250, 510), sign('d', 195, 590), sign('e', 200, 300)];
  const out = placeLegendSigns(signs, bodies, PHONE);
  clean(out, bodies, PHONE, 'busier crowd'); nextToPins(out, signs, 'busier crowd');
}

// 3d. no clear spot beside the pin even for the picture, but the pin's own place is clear: the picture on the pin
{
  const ring = [{ x: 140, y: 440, w: 120, h: 40 }, { x: 140, y: 520, w: 120, h: 40 }, { x: 140, y: 480, w: 42, h: 40 }, { x: 218, y: 480, w: 42, h: 40 }];
  const out = placeLegendSigns([sign('a', 200, 500)], ring, PHONE), p = out.get('a');
  ok(p.pos === 'at' && p.form === 'picture' && Math.abs(p.x + p.w / 2 - 200) < 0.01 && Math.abs(p.y + p.h / 2 - 500) < 0.01, 'boxed in tight: the picture on its pin');
  clean(out, ring, PHONE, 'boxed in tight');
}

// 4a. room beside the pin for the name but not the full sign: the picture and the name ("LEGENDARY:" drops)
{
  const walls = [{ x: 0, y: 0, w: 390, h: 400 }, { x: 0, y: 600, w: 390, h: 244 }, { x: 0, y: 400, w: 125, h: 200 }, { x: 275, y: 400, w: 115, h: 200 }];   // a 150 px wide gap: the name (120) fits, the full sign (190) does not
  const out = placeLegendSigns([sign('a', 200, 500)], walls, PHONE), p = out.get('a');
  ok(p.form === 'name' && p.w === 120, 'room for the name only: the picture and the name (' + p.form + ')');
  clean(out, walls, PHONE, 'name only');
}

// 4. no room for the name either: the picture alone, still clear
{
  const walls = [{ x: 0, y: 0, w: 390, h: 455 }, { x: 0, y: 545, w: 390, h: 299 }, { x: 0, y: 455, w: 150, h: 90 }, { x: 250, y: 455, w: 140, h: 90 }];
  const out = placeLegendSigns([sign('a', 200, 500)], walls, PHONE), p = out.get('a');
  ok(p.form === 'picture' && !p.hidden && p.w === 35, 'boxed in: the picture alone');
  clean(out, walls, PHONE, 'boxed in');
}

// 5. nowhere at all (the live run's corner by the Sound and menu buttons): the sign hides and takes no room; the pin
// still marks the item
{
  const out = placeLegendSigns([sign('a', 4, 10), sign('b', 200, 500)], [{ x: 0, y: 0, w: 390, h: 300 }], PHONE);
  ok(out.get('a').hidden === 'no room', 'nowhere: hidden, never over a panel');
  ok(!out.get('b').hidden && out.get('b').pos === 'up', 'nowhere: a hidden sign takes no room from the next');
}

// 5b. a pin the camera has left (the live run: two drops below the screen piled on each other at its edge): hidden
{
  const out = placeLegendSigns([sign('a', 30, 960), sign('b', 45, 975), sign('c', -20, 300)], [], PHONE);
  ok(['a', 'b', 'c'].every((k) => out.get(k).hidden === 'off screen'), 'off screen: every sign hidden');
}

// 5c. a pin under a HUD panel (the live run: a pin under the kill feed got a picture at the screen's edge): hidden, like a pin off screen
{
  const feed = { x: 8, y: 650, w: 374, h: 130 };
  const out = placeLegendSigns([sign('a', 345, 710), sign('b', 200, 500)], [feed], PHONE, [feed]);
  ok(out.get('a').hidden === 'under the HUD', 'under the feed: hidden');
  ok(!out.get('b').hidden, 'under the feed: a pin in view keeps its sign');
}

// 6. a pin at the screen edge: the sign stays on screen
{
  const out = placeLegendSigns([sign('a', 380, 300)], [], PHONE);
  clean(out, [], PHONE, 'edge');
}

// 7. the real Hud.placeLegends: two drops 20 px apart between two bodies at 390 wide
class Element {
  constructor() { this.style = {}; this.dataset = {}; this.cls = new Set(); this.on = {}; this.offsetHeight = 35; const s = this.cls; this.classList = { toggle: (c, on) => { if (on ?? !s.has(c)) s.add(c); else s.delete(c); }, contains: (c) => s.has(c), remove: (...cs) => cs.forEach((c) => s.delete(c)), add: (c) => s.add(c) }; }
  get offsetWidth() { return this.cls.has('short') && !this.cls.has('open') ? 35 : this.cls.has('nameonly') ? 120 : 190; }
  addEventListener(type, fn) { this.on[type] = fn; }
  fire(type, e = {}) { this.on[type]({ stopPropagation() {}, ...e }); }
  remove() { this.removed = true; }
}
{
  const hud = Object.create(Hud.prototype);
  Object.assign(hud, { w: 390, h: 844, legends: new Map(), tagRects: [{ x: 160, y: 380, w: 70, h: 18 }], rects: { board: { x: 8, y: 8, w: 200, h: 120 }, feed: null, btn0: { x: 330, y: 790, w: 50, h: 44 }, btn1: null },
    toScreen: (x, y, z) => ({ x: x * 100, y: z * 100 - y * 33 }) });   // 1 world unit = 100 px across; a body ~50 px tall, as measured live at 2.8x
  for (const [k, x, z] of [['d1', 1.95, 5.0], ['d2', 2.15, 5.05]]) { const lg = { sign: new Element(), pin: new Element(), x, z, gone: null, w: 0, h: 0 }; hud.wireLegend(lg); hud.legends.set(k, lg); }
  const pos = new Map([['h1', { x: 1.5, z: 5.1, state: 'alive', f: { status: 0 } }], ['h2', { x: 2.6, z: 5.05, state: 'alive', f: { status: 0 } }]]);
  hud.placeLegends(pos, 0);
  const rect = (lg) => { if (lg.sign.style.visibility === 'hidden') return null; const m = /translate\(([-\d.]+)px,([-\d.]+)px\)/.exec(lg.sign.style.transform); return { x: +m[1], y: +m[2], w: lg.sign.offsetWidth * 0.7, h: 35 * 0.7 }; };
  const [r1, r2] = [...hud.legends.values()].map(rect);
  const bodies = [...pos.values()].map((q) => bodyBox(hud.toScreen(q.x, 0, q.z), hud.toScreen(q.x, 1.5, q.z)));
  ok(r1 && r2, 'Hud: both signs shown');
  ok(!hit(r1, r2), 'Hud: the two signs apart');
  for (const [i, r] of [r1, r2].entries()) {
    ok(!bodies.some((b) => hit(r, b)), 'Hud: sign ' + i + ' covers no body');
    ok(!hit(r, hud.tagRects[0]) && !hit(r, hud.rects.board) && !hit(r, hud.rects.btn0), 'Hud: sign ' + i + ' covers no tag or panel');
    ok(onScreen(r, PHONE), 'Hud: sign ' + i + ' on screen');
  }
  const pin = [...hud.legends.values()][0].pin.style.transform;
  ok(pin === 'translate(195.0px,498.4px)', 'Hud: the pin stays on the item (' + pin + ')');
  ok(Array.isArray(hud.legendRects) && hud.legendRects.length === 2, 'Hud: the placed rects are exposed for review');
}

// 8. the real Hud: collision previews open during the announcement, then the sign and pin leave together
{
  const hud = Object.create(Hud.prototype);
  const walls = [{ x: 0, y: 0, w: 390, h: 455 }, { x: 0, y: 545, w: 390, h: 299 }, { x: 0, y: 455, w: 170, h: 90 }, { x: 230, y: 455, w: 160, h: 90 }];
  Object.assign(hud, { w: 390, h: 844, legends: new Map(), tagRects: walls, rects: {}, toScreen: (x, y, z) => ({ x: x * 100, y: z * 100 - y * 33 }) });
  const lg = { sign: new Element(), pin: new Element(), x: 2.0, z: 5.0165, gone: null, w: 0, h: 0 }; hud.wireLegend(lg); hud.legends.set('d', lg);
  const t0 = performance.now(), box = () => { const m = /translate\(([-\d.]+)px/.exec(lg.sign.style.transform); return { x: +m[1], w: lg.sign.offsetWidth * 0.7 }; };
  hud.placeLegends(new Map(), t0);
  ok(lg.sign.dataset.form === 'picture' && lg.sign.classList.contains('short') && !lg.sign.classList.contains('open'), 'boxed in on the page: the picture alone (' + lg.sign.dataset.form + ')');
  lg.sign.fire('pointerenter', { pointerType: 'touch' }); hud.placeLegends(new Map(), t0);
  ok(!lg.sign.classList.contains('open'), 'a touch passing over does not open it');
  lg.sign.fire('click'); hud.placeLegends(new Map(), performance.now());
  const b = box();
  ok(lg.sign.classList.contains('open') && b.w === 190 * 0.7, 'a tap opens the full sign');
  ok(b.x >= 6 && b.x + b.w <= 384, 'the opened sign stays on screen (' + b.x.toFixed(1) + '..' + (b.x + b.w).toFixed(1) + ')');
  lg.sign.fire('click'); hud.placeLegends(new Map(), performance.now());
  ok(!lg.sign.classList.contains('open'), 'a second tap closes the active preview');
  lg.sign.fire('pointerenter', { pointerType: 'mouse' }); hud.placeLegends(new Map(), performance.now());
  ok(lg.sign.classList.contains('open'), 'hover opens the active collision preview');
  hud.placeLegends(new Map(), lg.showUntil + 300);
  ok(lg.sign.removed && lg.pin.removed, 'the automatic deadline removes the complete overlay, including its pin');
  const full = { sign: new Element(), pin: new Element(), x: 2.0, z: 3.0, gone: null, w: 0, h: 0 }; hud.wireLegend(full); hud.legends.set('e', full);
  hud.tagRects = []; hud.legends.delete('d'); hud.placeLegends(new Map(), performance.now());
  full.sign.fire('click'); hud.placeLegends(new Map(), performance.now());
  ok(full.sign.dataset.form === 'full' && !full.sign.classList.contains('open') && full.openUntil === 0, 'a tap on a full sign does nothing');
}

console.log('arena-legend-place-case: ' + checks + ' checks OK');
