// Board 2's feed on a phone keeps its box within PHONE_MAX (176 px), the height the call to action reserves above it
// (arena.html feedReserve): when the newest slips would exceed it, the oldest drop out whole; the newest always shows; no
// slip is cut; the box carries data-reserve. Runs the real Feed on a stub document whose box height is the sum of its
// slips (11 px padding + 17.55 px a line, a line per 40 characters at 390, 6 px gaps), so long spoken lines push past
// the cap that a live 30 s fight never reached.
//   node near/web/arena-feed-cap-case.mjs
import assert from 'node:assert/strict';
import { Feed, PHONE_MAX } from './arena/feed.mjs';

let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };
const text = (n) => (n.children || []).reduce((t, c) => t + text(c), n.text || '');
const slipH = (li) => 11 + 17.55 * Math.max(1, Math.ceil(text(li).length / 40));
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this.attrs = {}; this.hidden = false; this._text = ''; this.classList = { add() {}, toggle() {}, remove() {} }; }
  get text() { return this._text; } set textContent(v) { this._text = String(v); this.children = []; } get textContent() { return text(this); }
  appendChild(c) { this.children.push(c); c.parentNode = this; return c; } append(...cs) { cs.forEach((c) => this.appendChild(c)); }
  replaceChildren(...cs) { this.children = []; this.append(...cs); } removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }
  get firstChild() { return this.children[0] || null; } setAttribute(k, v) { this.attrs[k] = v; }
  get offsetHeight() {   // the feed box: its chip (when shown) and its slips
    if (!this.children.some((c) => c.tag === 'ul')) return 0;
    const ul = this.children.find((c) => c.tag === 'ul'), chip = this.children.find((c) => c.tag === 'span');
    return (chip && !chip.hidden ? 24 : 0) + ul.children.reduce((h, li, i) => h + slipH(li) + (i ? 6 : 0), 0);
  }
}
const doc = { createElement: (t) => new El(t), createTextNode: (s) => Object.assign(new El('#text'), { _text: String(s) }) };
const feed = new Feed(doc, new El('div'), { name: (id) => ({ a: 'Satrenchi', b: 'Captain Banana Zone', c: 'Avichad' })[id] || id, colour: () => '#2a2622' });
feed.setNarrow(true);
ok(PHONE_MAX === 176 && feed.box.dataset.reserve === '176', 'a phone feed carries its reserve (176)');

// three short KO slips: one line each, well inside the cap: all three show
for (const [w, v] of [['a', 'b'], ['b', 'c'], ['c', 'a']]) feed.push({ kind: 'ko', who: w, victim: v });
ok(feed.list.children.length === 3 && feed.box.offsetHeight <= PHONE_MAX, 'short slips: all 3 show (' + feed.box.offsetHeight.toFixed(1) + ' px)');

// long spoken lines (4 lines each at 390): three of them would be ~250 px; the oldest drop out whole
const long = (n) => 'line ' + n + ': ' + 'the tide keeps every promise it makes to the shore, eventually, and so do I'.repeat(2);
for (let i = 1; i <= 3; i++) feed.push({ kind: 'say', who: 'a', text: long(i) });
ok(feed.box.offsetHeight <= PHONE_MAX, 'long lines: the box stays within the cap (' + feed.box.offsetHeight.toFixed(1) + ' px)');
ok(feed.list.children.length >= 1 && feed.list.children.length < 3, 'long lines: the oldest dropped out (' + feed.list.children.length + ' shown)');
const last = feed.list.children[feed.list.children.length - 1];
ok(text(last).includes('line 3:') && text(last).endsWith('eventually, and so do I”'), 'the newest slip shows, whole');
ok(feed.list.children.every((li) => /”$/.test(text(li))), 'every shown slip is whole (no slip cut)');

// one slip taller than the cap on its own: it still shows (the newest always shows)
feed.push({ kind: 'say', who: 'b', text: 'x'.repeat(400) });
ok(feed.list.children.length === 1 && text(feed.list.children[0]).includes('x'.repeat(400)), 'a single slip taller than the cap still shows, whole');

// desktop: no cap, no reserve
feed.setNarrow(false);
ok(feed.box.dataset.reserve === '' && feed.list.children.length > 1, 'desktop: no cap and no reserve (' + feed.list.children.length + ' slips)');

console.log('arena-feed-cap-case: ' + checks + ' checks OK');
