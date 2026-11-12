// The arena HUD of approved board 2 (direction C, "Wall sign"), its pure pieces: the name-tag circles, the crowd card,
// the merged feed's slips, the wall sign's boards, the layout beside board 1's panel, the sound button's two faces, the
// lives the circles read (caught up with the snapshot buffer) and the pre-jump card's timeline.
// Run: node near/web/arena-board2-case.mjs   (no browser; the browser pass is the reader's)
import assert from 'node:assert/strict';
import { circlesModel, circlesLabel, crowdGroups, cardSpot, REACH } from './arena/pips.mjs';
import { slip, nameColour, contrast, GLYPH, LINES, Feed } from './arena/feed.mjs';
import { boards, signBox, rowsFor, signUrl, WORDS, columnsHtml, Sign, nameHtml } from './arena/sign.mjs';
import { soundFace, COPY } from './arena/corner.mjs';
import { Lives } from './arena/lives.mjs';
import { pose, STAMP_MS, SHRINK_MS, LIFT_PX } from './arena/prejump.mjs';
import { hudLayout } from './arena/hud-layout.mjs';
let n = 0;

// ---- circles: start empty, fill green per KO, ringed when met, +N beyond
assert.equal(circlesModel(null, 2), null); assert.equal(circlesModel(0, 0), null); n++;
assert.deepEqual(circlesModel(2, 0), { n: 2, filled: 0, met: false, extra: 0 }); n++;
assert.deepEqual(circlesModel(2, 1), { n: 2, filled: 1, met: false, extra: 0 }); n++;
assert.deepEqual(circlesModel(2, 2), { n: 2, filled: 2, met: true, extra: 0 }); n++;
assert.deepEqual(circlesModel(1, 3), { n: 1, filled: 1, met: true, extra: 2 }); n++;
assert.equal(circlesLabel(circlesModel(3, 1)), 'predicts 3+ KOs, 1 so far'); n++;

// ---- the crowd rule: three or more within reach share a card, listed left to right; pairs keep their tags
const R = REACH.wide;
assert.deepEqual(crowdGroups([{ id: 'a', x: 100, y: 100 }, { id: 'b', x: 150, y: 110 }], R), []); n++;
assert.deepEqual(crowdGroups([{ id: 'c', x: 250, y: 100 }, { id: 'a', x: 100, y: 100 }, { id: 'b', x: 180, y: 120 }, { id: 'far', x: 700, y: 400 }], R), [['a', 'b', 'c']]); n++;
const row80 = [{ id: 'a', x: 100, y: 100 }, { id: 'b', x: 180, y: 100 }, { id: 'c', x: 260, y: 100 }];   // 80 px apart
assert.deepEqual(crowdGroups(row80, REACH.wide), [['a', 'b', 'c']]); assert.deepEqual(crowdGroups(row80, REACH.narrow), []); n++;
const view = { w: 1440, h: 900, top: 190, bottom: 820 };
const up = cardSpot([{ x: 700, y: 400 }, { x: 760, y: 410 }, { x: 820, y: 400 }], [], { w: 140, h: 70 }, view);
assert.equal(up.pos, 'up'); assert.ok(up.box.y + up.box.h <= 400); n++;
// a group under the sign: above would reach under it, so the card goes elsewhere
const nearTop = cardSpot([{ x: 700, y: 210 }, { x: 760, y: 215 }, { x: 820, y: 210 }], [], { w: 140, h: 70 }, view);
assert.notEqual(nearTop.pos, 'up'); assert.ok(nearTop.box.y >= view.top); n++;
// a fighter sitting where "above" would go pushes the card aside
const busy = cardSpot([{ x: 700, y: 500 }, { x: 760, y: 505 }, { x: 820, y: 500 }], [{ x: 760, y: 440 }], { w: 140, h: 70 }, view);
assert.notEqual(busy.pos, 'up'); n++;

// ---- the feed: one stack, the speaker set apart, one glyph per meaning
const name = (id) => ({ leeth: 'Leeth', sat: 'Satrenchi', lou: 'Lantern Lou', bz: 'Banana Zone', mw: 'Moonwood' })[id] || id;
const text = (s) => s.parts.map((p) => p.text).join('');
let s = slip({ kind: 'say', who: 'mw', emoji: '📚', text: 'Curve says you drift, Captain.' }, name);
assert.deepEqual([s.who, s.emoji, s.glyph, text(s)], ['Moonwood', '📚', null, '“Curve says you drift, Captain.”']); n++;
s = slip({ kind: 'say', who: 'mw', text: 'gm', status: 'blocked line' }, name);
assert.equal(text(s), '“gm” · blocked line'); n++;   // a blocked line says so (gate 6)
s = slip({ kind: 'ko', who: 'bz', victim: 'leeth' }, name);
assert.deepEqual([s.cls, s.who, s.glyph, text(s)], ['ko', 'Banana Zone', 'KO', 'KO’d Leeth']); n++;
s = slip({ kind: 'ko', who: 'bz', victim: 'leeth', ambush: true }, name); assert.equal(text(s), 'ambushed Leeth'); n++;
s = slip({ kind: 'leg', who: 'leeth', victim: 'sat', item: 'Stack Sats' }, name);
assert.deepEqual([s.cls, s.glyph, text(s)], ['leg', '◆', 'KO’d Satrenchi, who dropped Stack Sats']); n++;
s = slip({ kind: 'pred', who: 'lou', level: 2 }, name); assert.deepEqual([s.cls, s.glyph, text(s)], ['pred', '◎', 'predicts 2+ KOs']); n++;
s = slip({ kind: 'res', who: 'lou', level: 1, points: 20 }, name); assert.deepEqual([s.cls, s.glyph, text(s)], ['res', '✓', 'made 1+ KO: correct +20 points']); n++;
s = slip({ kind: 'escape', who: 'lou', hp: 4 }, name); assert.deepEqual([s.glyph, text(s)], [null, 'escaped at 4 HP']); n++;
assert.equal(new Set(Object.values(GLYPH)).size, Object.keys(GLYPH).length); n++;   // one meaning per symbol
assert.deepEqual(LINES, { wide: 5, narrow: 3 }); n++;
// no gambling word in any slip
for (const it of [{ kind: 'pred', who: 'lou', level: 3 }, { kind: 'res', who: 'lou', level: 3, points: 950 }])
  assert.doesNotMatch(text(slip(it, name)), /\b(bet|stake|pot|payout|terms)\b/i);
n++;
// the speaker's colour is the fighter's own, darkened until it reads on the slip
const paper = [0xfb, 0xf3, 0xe2], rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
for (const c of ['#F7CF6B', '#9FDCC5', '#A9D4F5', '#FFF8EA', '#D97A6E', '#3B2F25']) assert.ok(contrast(rgb(nameColour(c)), paper) >= 4.5, c);
assert.equal(nameColour(null), '#2a2622'); n++;

// ---- the wall sign: the hour board when the host has it, per side, n rows
const json = { day: '2026-11-12', most_kos: [{ persona: 'bz', house: true, kos: 7, lives: 2 }, { persona: 'lou', house: false, kos: 3, lives: 1 }],
  most_correct: [{ persona: 'lou', house: false, reward_points: 140, correct: 4 }],
  boards: { most_kos_hour: { players: [{ persona: 'lou', house: false, kos: 3, lives: 1 }, { persona: 'cass', house: false, kos: 2, lives: 1 }, { persona: 'sid', house: false, kos: 1, lives: 1 }, { persona: 'pip', house: false, kos: 1, lives: 2 }],
    house: [{ persona: 'bz', house: true, kos: 7, lives: 2 }] },
    most_correct_day: { players: [{ persona: 'lou', house: false, reward_points: 140, correct: 4 }], house: [{ persona: 'sail', house: true, reward_points: 120, correct: 6 }] } } };
let b = boards(json, 'players', 3);
assert.deepEqual(b.ko.rows, [{ id: 'lou', num: 3 }, { id: 'cass', num: 2 }, { id: 'sid', num: 1 }]);
assert.deepEqual(b.pr.rows, [{ id: 'lou', num: 140, count: 4 }]); n++;
b = boards(json, 'house', 1); assert.deepEqual([b.ko.rows, b.pr.rows], [[{ id: 'bz', num: 7 }], [{ id: 'sail', num: 120, count: 6 }]]); n++;
// a host without the boards object: both boards empty, never the day's KOs under "this hour"
b = boards({ day: '2026-11-12', most_kos: json.most_kos, most_correct: json.most_correct }, 'house', 3);
assert.deepEqual(b, { ko: { rows: [] }, pr: { rows: [] } }); n++;
assert.deepEqual(boards(null, 'players', 3), { ko: { rows: [] }, pr: { rows: [] } }); assert.equal(WORDS.koWhen, 'this hour'); n++;
assert.equal(rowsFor(1440, 900), 3); assert.equal(rowsFor(1440, 760), 1); assert.equal(rowsFor(390, 844), 1); n++;
assert.deepEqual(signBox({ w: 1440, h: 900 }, 1440), { x: 400, w: 640 }); n++;
assert.deepEqual(signBox({ w: 390, h: 844 }, 390), { x: 8, w: 374 }); n++;
const withPanel = signBox({ w: 1440, h: 900 }, 1440 - 472); assert.ok(withPanel.x + withPanel.w <= 1440 - 472); n++;   // centred in the free width
assert.equal(signUrl('wss://neartrenchies.xyz/arena-ws'), 'https://neartrenchies.xyz/house/leaderboards.json');
assert.equal(signUrl('ws://127.0.0.1:8765'), 'http://127.0.0.1:8765/house/leaderboards.json'); n++;

// ---- beside board 1's panel (builder-c's contract: [data-arena-panel] open; .edge-tab / .pill / .toast closed)
const corner = { w: 250, h: 40 };
let L = hudLayout({ w: 1440, h: 900 }, { open: null, closed: [] }, corner);
assert.deepEqual([L.right, L.bottom, L.free, L.feedHidden], [16, 16, 1440, false]); n++;
L = hudLayout({ w: 1440, h: 900 }, { open: { x: 968, y: 12, w: 460, h: 876 }, closed: [] }, corner);
assert.deepEqual([L.right, L.free, L.pan], [1440 - 968 + 16, 952, 244]); n++;   // the sheet's 952 px free width; the ring re-centres in it
L = hudLayout({ w: 390, h: 844 }, { open: { x: 0, y: 290, w: 390, h: 554 }, closed: [] }, corner);
assert.deepEqual([L.bottom, L.feedHidden], [844 - 290 + 8, true]); n++;
L = hudLayout({ w: 390, h: 844 }, { open: null, closed: [{ x: 12, y: 766, w: 366, h: 64 }] }, corner);   // the phone pill
assert.equal(L.bottom, 844 - 766 + 8); n++;
L = hudLayout({ w: 1440, h: 900 }, { open: null, closed: [{ x: 1344, y: 120, w: 96, h: 40 }] }, corner);   // the desktop tab is far from the buttons
assert.equal(L.bottom, 16); n++;

// ---- sound: two faces, both with words; before the first click it reads "Sound" (about to play)
assert.deepEqual([soundFace('on').label, soundFace('on').pressed, soundFace('on').off], ['Sound', 'false', false]);
assert.deepEqual([soundFace('muted').label, soundFace('muted').pressed, soundFace('muted').aria], ['Muted', 'true', COPY.sound.offAria]);
assert.equal(soundFace('waiting for a click').label, 'Sound'); n++;
assert.equal(COPY.how.length, 8); assert.doesNotMatch(JSON.stringify(COPY), /\b(bet|stake|pot|payout|terms)\b/i); n++;

// ---- lives: applied only once the drawn picture caught up; one "correct" per life, none for a life met before load
const lv = new Lives();
lv.receive({ lou: { life: 'lou:1', level: 2, kos: 2, points: 357 }, cass: { life: 'cass:1', level: 1, kos: 0, points: 150 } }, 1000);
assert.deepEqual(lv.advance(1000), []); assert.equal(lv.get('lou').kos, 2); n++;   // met before the page saw it: no line
lv.receive({ lou: { life: 'lou:1', level: 2, kos: 2, points: 357 }, cass: { life: 'cass:1', level: 1, kos: 1, points: 150 } }, 2000);
assert.deepEqual(lv.advance(1900), []); assert.equal(lv.get('cass').kos, 0); n++;   // still behind the buffer
assert.deepEqual(lv.advance(2150), [{ id: 'cass', life: 'cass:1', level: 1, points: 150 }]); assert.equal(lv.get('cass').kos, 1); n++;
lv.receive({ cass: { life: 'cass:1', level: 1, kos: 2, points: 150 } }, 3000);
assert.deepEqual(lv.advance(3200), []); n++;   // already met this life
lv.receive({ cass: { life: 'cass:2', level: 1, kos: 1, points: 150 } }, 4000);
assert.deepEqual(lv.advance(4200), [{ id: 'cass', life: 'cass:2', level: 1, points: 150 }]); n++;   // a new life is met again
lv.receive(null, 5000); assert.equal(lv.get('cass'), null); n++;

// ---- the pre-jump: stamps above the drop point, then shrinks into the landing spot and fades
const from = { x: 500, y: 400 }, to = { x: 510, y: 330 };
assert.equal(pose(-1, from, to), null);
let p = pose(0, from, to); assert.deepEqual([p.x, p.y, p.scale, p.opacity], [500, 400 - LIFT_PX, 1.4, 0]); n++;
p = pose(STAMP_MS, from, to); assert.deepEqual([p.x, p.y, p.scale, p.opacity], [500, 400 - LIFT_PX, 1, 1]); n++;
p = pose(STAMP_MS + SHRINK_MS, from, to); assert.deepEqual([p.x, p.y, +p.scale.toFixed(3), p.opacity], [510, 330, 0.4, 0]); n++;

// ---- review round 1 (critic-b @ a5b203f)
// L4: a 0-KO row (or 0 points) is not a place on the board
const zero = { boards: { most_kos_hour: { players: [{ persona: 'ann', kos: 3, lives: 1 }, { persona: 'leeth', kos: 0, lives: 1 }], house: [] },
  most_correct_day: { players: [{ persona: 'ann', reward_points: 0, correct: 0 }], house: [] } } };
assert.deepEqual(boards(zero, 'players', 3), { ko: { rows: [{ id: 'ann', num: 3 }] }, pr: { rows: [] } }); n++;
// L1: the switch is two toggle buttons, the shown side pressed (no tab role without a tab panel)
const opts = { side: 'house', short: false, offline: false, name: (id) => id, face: () => null, dev: () => false };
let html = columnsHtml(boards(json, 'house', 3), opts);
assert.match(html.ko, /data-side="house" aria-pressed="true"/); assert.match(html.ko, /data-side="players" aria-pressed="false"/);
assert.doesNotMatch(html.ko + html.pr, /role="tab"/); n++;
// M3: no arena running says so in both boards (never an empty board that reads as "no KOs")
html = columnsHtml(boards(json, 'players', 3), { ...opts, offline: true });
assert.match(html.ko, /No arena running/); assert.match(html.pr, /No arena running/); assert.doesNotMatch(html.ko, /class="nm"/); n++;
// M2: the sign says in place that a life counts when it ends (the boards trail the tags until then)
assert.equal(WORDS.counted, 'Counted as each life ends.'); n++;
// H1: a narrow sign gets the short predictions title (the CSS drops points, rank and face before the name)
assert.match(columnsHtml(boards(json, 'players', 3), { ...opts, short: true }).pr, /class="ttl">Predictions </); n++;
// L3: "autopilot" is said once, as the feed's chip, not after every house line
const fake = () => { const el = { children: [], style: {}, dataset: {}, className: '', hidden: false, textContent: '', attrs: {},
  setAttribute(k, v) { this.attrs[k] = v; }, appendChild(c) { this.children.push(c); return c; }, append(...c) { this.children.push(...c); },
  replaceChildren(...c) { this.children = c; }, classList: { add() {}, toggle() {} } }; return el; };
const doc = { createElement: fake, createTextNode: (t) => ({ textContent: t }) };
const fd = new Feed(doc, fake(), { name: (id) => id, colour: () => '#2a2622' });
fd.push({ kind: 'say', who: 'leeth', text: 'Ether Stack.', status: 'autopilot' });
fd.push({ kind: 'say', who: 'leeth', text: 'Back in a cycle.', status: 'blocked line' });
assert.equal(fd.chip.hidden, false); assert.equal(fd.chip.textContent, 'House on autopilot');
assert.equal(fd.items[0].status, null); assert.equal(fd.items[1].status, 'blocked line'); n++;   // other statuses stay on their line
fd.items = []; fd.render(); assert.equal(fd.chip.hidden, true); n++;
// a feed line naming a DEV fighter draws its DEV chip (the autopilot chip element must not shadow that method)
const devFeed = new Feed(doc, fake(), { name: (id) => id, colour: () => '#2a2622', dev: (id) => id.startsWith('dev-') });
devFeed.push({ kind: 'ko', who: 'dev-ann', victim: 'leeth' });
assert.ok(devFeed.list.children[0].children.some((c) => c.className === 'dev' && c.textContent === 'DEV')); n++;

// a name that arrives after the boards (the social frame's names map) redraws its sign row
const stubs = {}, signEl = { style: {}, dataset: {}, classList: { toggle() {} }, set innerHTML(v) {}, addEventListener() {}, querySelector: (q) => (stubs[q] = stubs[q] || { innerHTML: '', setAttribute() {} }),
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) };
const names = {};
const sg = new Sign({ createElement: () => signEl }, { appendChild() {} }, { name: (id) => names[id] || id, face: () => null });
sg.layout({ w: 1440, h: 900 }, 1440); sg.setData(json);
assert.match(stubs['[data-board="ko"]'].innerHTML, />lou</);
names.lou = 'Lantern Lou'; sg.render();
assert.match(stubs['[data-board="ko"]'].innerHTML, />Lantern Lou</); n++;

// H1 rounds 2-3: the sign fits its names (the sheet: a name is never cut). A name that would not fit drops rank, face and
// "points" first and wraps between words onto 2 lines (tight); one that still needs more takes the whole row (stack).
const fitSign = (w) => {   // w: the name's room as drawn (loose), tight (2 lines beside its numbers), stacked; a 180 px name
  const cls = new Set(), el = { classList: { add: (...c) => c.forEach((x) => cls.add(x)), remove: (...c) => c.forEach((x) => cls.delete(x)), contains: (c) => cls.has(c) },
    querySelectorAll: () => [{ scrollWidth: 180, get clientWidth() { return cls.has('tight') ? 999 : w.loose; },
      get scrollHeight() { return 2 * 16 + (cls.has('stack') ? 0 : w.extraLines * 16); }, clientHeight: 2 * 16 }] };
  const sgn = Object.create(Sign.prototype); sgn.el = el; sgn.fit(); return [...cls].sort().join(' ');
};
assert.equal(fitSign({ loose: 200, extraLines: 0 }), '');               // fits as drawn: the sheet's full row stays
assert.equal(fitSign({ loose: 120, extraLines: 0 }), 'tight');          // rank, face and points drop; 2 lines suffice
assert.equal(fitSign({ loose: 120, extraLines: 1 }), 'stack tight'); n++;   // still more: the name takes the whole row

// board2-followup (critic-b round 4 LOWs): the DEV chip stays with the name's last word, and a long single word shows a
// hyphen where it breaks (soft hyphens), never a bare cut
assert.equal(nameHtml('Bartholomew Longname of the Tide', true), 'Bartholomew Longname of the <span class="nb">Tide&nbsp;<span class="dev">DEV</span></span>');
assert.equal(nameHtml('Lantern Lou', false), 'Lantern Lou'); n++;
const sup = nameHtml('Supercalifragilisticexpialidocious', true);
assert.match(sup, /&shy;/); assert.equal(sup.replace(/<[^>]+>/g, '').replace(/&shy;|&nbsp;DEV/g, ''), 'Supercalifragilisticexpialidocious');
assert.match(sup, /<span class="nb">[a-z]{3,}&nbsp;<span class="dev">DEV<\/span><\/span>$/); n++;   // the chip keeps a word piece with it
assert.equal(nameHtml('A<b>', false), 'A&lt;b>'); n++;   // still escaped

console.log('arena-board2-case: ' + n + ' checks OK');
