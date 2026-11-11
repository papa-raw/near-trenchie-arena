// Big moments for the ticker (near/web/arena/moments.mjs) and the ticker's tag + emoji line (social.mjs tickerParts).
//   node near/web/arena-moments-case.mjs
import assert from 'node:assert/strict';
import { Moments, ESCAPE_TICKS } from './arena/moments.mjs';
import { tickerParts, tickerWidth, tickerBottom } from './arena/social.mjs';

const ITEMS = { 'leg-laser-eyes': { name: 'LASER EYES', tier: 'legendary', origin: 'house:laser-sailor' },
                'c-swing': { name: 'Swing', tier: 'common', origin: 'starter' } };
const tag = (id) => ({ 'laser-sailor': 'Sailor', 'tommy-leeth': 'Leeth', 'avichad': 'Avichad' }[id] || id);
const F = (id, hp, target = null, items = {}) => ({ id, hp, status: 0, target, items });
const snap = (tick, fighters, drops = [], events = []) => ({ tick, fighters, drops, events });
let n = 0;

{ // an ambush: the victim was fighting someone else when its killer struck; a straight duel KO is no ambush
  const m = new Moments(ITEMS, tag);
  m.onSnapshot(snap(10, [F('tommy-leeth', 90, 'avichad'), F('laser-sailor', 80, 'tommy-leeth'), F('avichad', 70, 'tommy-leeth')]));
  const out = m.onEvent({ kind: 'ko', fighter: 'tommy-leeth', source: 'laser-sailor' }, snap(11, []));
  assert.equal(out.length, 1); assert.equal(out[0].kind, 'ambush'); assert.equal(out[0].text, 'AMBUSHES Leeth'); n++;
  assert.deepEqual(m.onEvent({ kind: 'ko', fighter: 'avichad', source: 'tommy-leeth' }, snap(12, [])), []); n++;
}
{ // a legendary on the sand names who dropped it; a steal names the owner it was taken from; the owner's own grab is no steal
  const m = new Moments(ITEMS, tag);
  m.onSnapshot(snap(20, [F('laser-sailor', 10, 'avichad', { trinket: 'leg-laser-eyes' }), F('avichad', 50, 'laser-sailor')]));
  m.onEvent({ kind: 'ko', fighter: 'laser-sailor', source: 'avichad' }, snap(21, []));
  const drop = m.onSnapshot(snap(22, [F('avichad', 50)], [{ key: 'd1', item: 'leg-laser-eyes' }]));
  assert.equal(drop[0].kind, 'legendary_drop'); assert.equal(drop[0].text, 'DROPS LASER EYES'); assert.equal(drop[0].tag, 'Sailor'); n++;
  assert.deepEqual(m.onSnapshot(snap(23, [F('avichad', 50)], [{ key: 'd1', item: 'leg-laser-eyes' }])), []); n++;   // once
  const steal = m.onEvent({ kind: 'grab', fighter: 'avichad', row: 'leg-laser-eyes' }, snap(24, []));
  assert.equal(steal[0].text, 'STEALS LASER EYES from Sailor'); n++;
  assert.deepEqual(m.onEvent({ kind: 'grab', fighter: 'laser-sailor', row: 'leg-laser-eyes' }, snap(25, [])), []); n++;
  assert.deepEqual(m.onEvent({ kind: 'grab', fighter: 'avichad', row: 'c-swing' }, snap(26, [])), []); n++;
}
{ // a near-death escape: at or under 10% of max HP and still standing 3 s later, once a life; a KO in between is no escape
  const m = new Moments(ITEMS, tag);
  m.onSnapshot(snap(100, [F('avichad', 100)]));
  m.onSnapshot(snap(101, [F('avichad', 8)]));
  assert.deepEqual(m.onSnapshot(snap(100 + ESCAPE_TICKS, [F('avichad', 8)])), []); n++;
  const esc = m.onSnapshot(snap(101 + ESCAPE_TICKS, [F('avichad', 12)]));
  assert.equal(esc[0].kind, 'near_death'); assert.equal(esc[0].text, 'ESCAPES at 12 HP'); n++;
  m.onSnapshot(snap(300, [F('avichad', 5)]));
  assert.deepEqual(m.onSnapshot(snap(300 + ESCAPE_TICKS + 5, [F('avichad', 5)])), []); n++;          // once a life
  const k = new Moments(ITEMS, tag);
  k.onSnapshot(snap(1, [F('avichad', 100)])); k.onSnapshot(snap(2, [F('avichad', 5)]));
  k.onEvent({ kind: 'ko', fighter: 'avichad', source: null }, snap(3, []));
  assert.deepEqual(k.onSnapshot(snap(2 + ESCAPE_TICKS + 1, [F('avichad', 100)])), []); n++;
}
{ // the ticker line: tag + emoji + text, the status after it; a moment: tag + glyph + text
  const roster = [{ trenchieId: 'avichad', tag: 'Avichad', name: 'Avichad' }];
  const say = tickerParts({ type: 'say', row: { who: 'avichad', text: 'Ship something.', emoji: '🚢' } }, roster);
  assert.deepEqual(say.parts.map((p) => p[0]), ['Avichad', '🚢', 'Ship something.']); n++;
  const old = tickerParts({ type: 'say', row: { who: 'avichad', text: 'gm', blocked: true } }, roster);
  assert.deepEqual(old.parts.map((p) => p[0]), ['Avichad', 'gm · blocked line']); n++;
  const mo = tickerParts({ type: 'moment', m: { kind: 'ambush', fighter: 'avichad', tag: 'Avichad', glyph: '▼', text: 'AMBUSHES Leeth' } }, roster);
  assert.deepEqual(mo.parts.map((p) => p[0]), ['Avichad', '▼', 'AMBUSHES Leeth']); n++;
}
{ // N1: the ticker ends before the first HUD button on its right, at 390 and at 1440
  assert.equal(tickerWidth(390, { btn0: { x: 300, y: 790, w: 40, h: 40 }, btn1: { x: 346, y: 790, w: 40, h: 40 } }), 300 - 8 - 12); n++;
  assert.equal(tickerWidth(1440, { btn0: { x: 1340, y: 840, w: 40, h: 40 } }), 560); n++;
  assert.equal(tickerWidth(390, {}), 390 - 24); n++;
}
{ // the ticker stands on the frozen feed's full reserved top: a KO line more does not move it (the button never hops)
  const empty = { x: 16, y: 860, w: 120, h: 24 }, full = { x: 16, y: 784, w: 300, h: 100 };   // same bottom (884)
  assert.equal(tickerBottom(900, empty, false), tickerBottom(900, full, false)); n++;
  assert.equal(tickerBottom(900, full, false), 900 - 784 + 8); n++;
  assert.equal(tickerBottom(844, { x: 10, y: 800, w: 200, h: 34 }, true), tickerBottom(844, { x: 10, y: 782, w: 260, h: 52 }, true)); n++;
}
console.log(n + ' PASS, 0 FAIL');
