// Checked persona metadata and guarded speech in the B2 a v3.1 ticker-and-tag treatment (Battle mode, Pat 2026-11-11:
// "speech bubbles shouldn't crowd the arena, they should be on the side. but we can have emojis with the fighters (so we
// know who is screaming)"). A spoken line goes only in the ticker, as tag + emoji + text; over the speaker's name tag its
// emoji floats for SAY_EMOJI_MS. The ticker also carries the big moments the frozen ticker art has no line for
// (moments.mjs). These fields are presentation data. They never enter the deterministic tick buffer.
import { tagText } from './names.mjs';

export const SAY_EMOJI_MS = 3000;       // how long the speaker's emoji floats over its tag
const FADE_MS = 500;                     // the last half second fades out
const INK = '#3B2F25', HALO = '1px 1px #FFF8E6,-1px -1px #FFF8E6,1px -1px #FFF8E6,-1px 1px #FFF8E6';
const GLYPH_INK = { '▼': '#C7462E', '◆': '#9E6A12', '✚': '#3E8E73' };   // the frozen ticker's KO red and drop gold

const overlap = (a, b) => Math.min(a.x + a.w, b.x + b.w) > Math.max(a.x, b.x) && Math.min(a.y + a.h, b.y + b.h) > Math.max(a.y, b.y);
export function placeSpeechPanel(anchor, size, tags, width, height, cards = []) {
  const margin = 8, gap = 6, w = Math.min(size.w, width - 2 * margin), h = Math.min(size.h, height - 2 * margin);
  const obstacles = [...tags, ...cards];
  const xs = [anchor.x + (anchor.w - w) / 2, anchor.x - w - gap, anchor.x + anchor.w + gap, margin, width - w - margin];
  const ys = new Set([anchor.y - h - gap, anchor.y + anchor.h + gap]);
  for (const rect of obstacles) { ys.add(rect.y - h - gap); ys.add(rect.y + rect.h + gap); }
  let best = null, bestDistance = Infinity;
  for (const x of xs) for (const y of ys) {
    const box = { x: Math.max(margin, Math.min(width - w - margin, x)), y: Math.max(margin, Math.min(height - h - margin, y)), w, h };
    const distance = (box.x + w / 2 - anchor.x - anchor.w / 2) ** 2 + (box.y + h / 2 - anchor.y - anchor.h / 2) ** 2;
    if (distance < bestDistance && !obstacles.some((rect) => overlap(box, rect))) { best = box; bestDistance = distance; }
  }
  return best;
}

// The ticker's lines, newest last: a spoken row is [tag, emoji, text · status]; a moment is [tag, glyph, text].
export function tickerParts(item, roster) {
  if (item.type === 'moment') {
    const m = item.m;
    return { who: m.fighter, parts: [...(m.tag ? [[m.tag, INK, true]] : []), [m.glyph, GLYPH_INK[m.glyph] || INK], [m.text, INK]] };
  }
  const r = item.row;
  const status = r.muted ? r.label || 'guard list missing' : r.blocked ? 'blocked line' + (r.label ? ' · ' + r.label : '') : r.label;
  return { who: r.who, parts: [[tagText(roster, r.who), INK, true], ...(r.emoji ? [[r.emoji, null]] : []),
    [r.text + (status ? ' · ' + status : ''), INK]] };
}

// The ticker's width: from its left margin to the first HUD button on its right (at 390 px the last line ran
// under the mute/menu buttons), never wider than 560 px.
export const TICKER_LEFT = 12, BUTTON_GAP = 8, TICKER_MAX = 560;
export function tickerWidth(hudW, rects) {
  const lefts = ['btn0', 'btn1'].map((k) => rects && rects[k]).filter(Boolean).map((r) => r.x);
  const right = lefts.length ? Math.min(...lefts) - BUTTON_GAP : hudW - TICKER_LEFT;
  return Math.max(120, Math.min(TICKER_MAX, right - TICKER_LEFT));
}

// Where the ticker's bottom sits: on the frozen feed's FULL reserved top (it grows to 3 KO lines, 2 on a phone), never
// its live top, so the ticker and everything placed around it (the snap-in button) stand still from the first frame
// (anchored to the live top, the ticker slid up as KO lines came in and the button hopped at ~8 s).
export const FEED_RESERVE = { wide: 100, narrow: 52 };      // the same reserve arena.html gives the frozen feed
export function tickerBottom(hudH, feedRect, narrow) {
  if (!feedRect) return 74;
  const top = Math.min(feedRect.y, feedRect.y + feedRect.h - (narrow ? FEED_RESERVE.narrow : FEED_RESERVE.wide));
  return Math.max(12, hudH - top + 8);
}

export class Social {
  constructor(KITS, root) {
    this.KITS = KITS; this.root = root; this.rows = []; this.items = []; this.latest = new Map(); this.marks = new Map();
    this.narrow = false;
    this.feed = document.createElement('div'); this.feed.className = 'arena-say-feed';
    this.feed.setAttribute('role', 'log'); this.feed.setAttribute('aria-label', 'Trenchie banter and big moments');
    this.feed.style.cssText = 'position:absolute;left:' + TICKER_LEFT + 'px;max-width:min(' + TICKER_MAX + 'px,calc(100vw - 24px));font:700 17px/1.4 "Space Mono",monospace;color:' + INK + ';text-shadow:' + HALO + ';overflow-wrap:anywhere;pointer-events:none;';
    this.layer = document.createElement('div'); this.layer.className = 'arena-say-layer';
    this.layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:2;';
    root.appendChild(this.feed); root.appendChild(this.layer);
  }
  roster() { return [...this.KITS.roster, ...(this.KITS.players || [])]; }
  apply(value) {
    if (value === null) { this.KITS.players = []; this.rows = []; this.items = []; this.latest.clear(); this.feed.replaceChildren(); return; }
    if (value.version !== 1 || !Array.isArray(value.players) || !Array.isArray(value.feed)) throw new Error('Unsupported arena social metadata');
    this.KITS.players = value.players;
    const previous = new Set(this.rows.map((r) => r.id)), now = performance.now();
    this.rows = value.feed;
    for (const row of this.rows) if (!previous.has(row.id)) {
      this.latest.set(row.who, { ...row, at: now });
      this.items.push({ type: 'say', row, at: now });
    }
    this.trim(); this.render();
  }
  moment(m) { this.items.push({ type: 'moment', m, at: performance.now() }); this.trim(); this.render(); }
  trim() { if (this.items.length > 24) this.items.splice(0, this.items.length - 24); }
  name(id) { return this.roster().find((r) => r.trenchieId === id)?.name || id; }
  render() {
    const roster = this.roster();
    this.feed.replaceChildren(...this.items.slice(this.narrow ? -2 : -3).map((item) => {
      const { who, parts } = tickerParts(item, roster), el = document.createElement('div');
      if (item.type === 'say') el.dataset.feedId = String(item.row.id); else el.dataset.moment = item.m.kind;
      if (who) el.dataset.fighterId = who;
      el.replaceChildren(...parts.map(([text, color, isName], i) => {
        const span = document.createElement('span'); span.textContent = (i ? ' ' : '') + text;
        if (color) span.style.color = color;
        if (isName) span.dataset.nm = '1';
        return span;
      }));
      return el;
    }));
  }
  // who is speaking now: their emoji floats over their tag, so their tag must show (hud.mjs tags)
  speaking(now) {
    const out = new Set();
    for (const [id, row] of this.latest) if (now - row.at <= SAY_EMOJI_MS) out.add(id);
    return out;
  }
  frame(pos, hud, now) {
    const narrow = hud.w < 600;
    if (narrow !== this.narrow) { this.narrow = narrow; this.render(); }
    const panels = ['board', 'banner', 'feed', 'btn0', 'btn1'].map((k) => hud.rects[k]).filter(Boolean);
    const seen = new Set(), bottom = hud.rects.feed, obstacles = [...(hud.tagRects || []), ...panels];
    this.feed.style.bottom = tickerBottom(hud.h, bottom, narrow) + 'px';
    this.feed.style.maxWidth = tickerWidth(hud.w, hud.rects) + 'px';
    this.feed.style.fontSize = narrow ? '15px' : '17px';
    for (const [id, q] of pos) {
      const row = this.latest.get(id), anchor = obstacles.find((r) => r.id === id);
      const age = row ? now - row.at : Infinity;
      if (!row || !row.emoji || age > SAY_EMOJI_MS || q.f.status === 2 || !anchor) continue;
      let el = this.marks.get(id);
      if (!el) {
        el = document.createElement('div'); el.className = 'say-emoji'; el.setAttribute('data-fighter-id', id);
        el.setAttribute('aria-hidden', 'true');
        el.style.cssText = 'position:absolute;line-height:1;text-shadow:' + HALO + ';';
        this.layer.appendChild(el); this.marks.set(id, el);
      }
      if (el.textContent !== row.emoji) el.textContent = row.emoji;
      el.dataset.feedId = String(row.id);
      el.style.fontSize = narrow ? '24px' : '30px';
      el.style.display = 'block';
      el.style.opacity = String(Math.max(0, Math.min(1, (SAY_EMOJI_MS - age) / FADE_MS)));
      seen.add(id);
      // over its own name tag first; beside it when another tag or a card is in the way; never over either
      const box = placeSpeechPanel(anchor, { w: el.offsetWidth, h: el.offsetHeight }, obstacles, hud.w, hud.h, hud.cardRects || []);
      if (!box) { el.style.display = 'none'; continue; }     // no clear spot: the ticker line still names the speaker
      el.style.left = box.x + 'px'; el.style.top = box.y + 'px'; obstacles.push(box);
    }
    for (const [id, el] of this.marks) if (!seen.has(id)) { el.remove(); this.marks.delete(id); }
  }
}
