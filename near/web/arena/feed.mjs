// The arena feed: one stack of paper slips bottom-left, newest last, older ones fading (approved board 2, direction C;
// Pat's items 3 and 4: "two UI feeds that should have been merged", "it's not clear who is talking"). Speech and events
// share it. The speaker's name is bold in its fighter's colour; speech follows its emoji in quotes; an event carries one
// glyph: KO (red edge), ◎ predicts and ✓ correct (green edge), ◆ legendary (gold edge). One meaning per symbol; an
// escape has no glyph. 5 lines at 1440, 3 on a phone. Presentation only: nothing here enters the tick buffer.

export const GLYPH = { ko: '▼', pred: '◎', res: '✓', leg: '◆', escape: '✚' };   // ebb97a0's line marks: KO red, legendary gold, escape green
export const LINES = { wide: 5, narrow: 3 };
// A phone's feed box never grows past this (three two-line slips, 3 x 46 + 2 x 6 gaps, and the autopilot chip, 24): when
// the newest slips would, the oldest drops out whole (no slip is ever cut). The call to action reserves exactly this
// height above the feed (arena.html, data-reserve), so it keeps one spot through a fight.
export const PHONE_MAX = 176;
const PAPER = '#fbf3e2', INK = '#2a2622';

// ---- colour: a fighter's own colour (its first palette colour), darkened until it reads on the slip (WCAG AA, 4.5:1)
const hex = (h) => { const m = /^#?([0-9a-f]{6})$/i.exec(String(h || '').trim()); return m ? [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16)) : null; };
const lum = (rgb) => { const c = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
export const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
export function nameColour(base) {
  const rgb = hex(base); if (!rgb) return INK;
  const bg = hex(PAPER);
  for (let k = 1; k >= 0.2; k -= 0.05) {
    const c = rgb.map((v) => Math.round(v * k));
    if (contrast(c, bg) >= 4.5) return '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');
  }
  return INK;
}

// ---- the slip's parts. item: one of
//   {kind:'say', who, emoji, text, status}       a guarded spoken line (status: a guard or budget label, shown after it)
//   {kind:'ko', who, victim, ambush}              who KO'd victim (who null: victim was knocked out of the ring)
//   {kind:'leg', who, victim, item, steal, from}  a KO that dropped a legendary, or a legendary grabbed (steal)
//   {kind:'pred', who, level}                     a life starts predicting level+ KOs
//   {kind:'res', who, level}                      the prediction met: correct
//   {kind:'escape', who, hp}                      a near-death escape
// name(id) -> the trenchie's name (never an id). Returns {cls, who, glyph, parts:[{text, who?, kind?}]}.
const kos = (n) => n + '+ KO' + (n === 1 ? '' : 's');
export function slip(item, name) {
  const who = item.who != null ? name(item.who) : null;
  switch (item.kind) {
    case 'say': return { cls: 'say', who, glyph: null, emoji: item.emoji || null, parts: [{ text: item.text }, ...(item.status ? [{ text: ' · ' + item.status, kind: 'status' }] : [])] };
    case 'ko': return item.who == null
      ? { cls: 'ko', who: name(item.victim), glyph: GLYPH.ko, parts: [{ text: 'KNOCKED OUT' }] }
      : { cls: 'ko', who, glyph: GLYPH.ko, parts: [{ text: item.ambush ? 'AMBUSHES ' : 'KO ' }, { text: name(item.victim), who: item.victim }] };
    case 'leg': return item.steal
      ? { cls: 'leg', who, glyph: GLYPH.leg, parts: [{ text: 'STEALS ' }, { text: item.item, kind: 'legn' }, ...(item.from ? [{ text: ' from ' }, { text: name(item.from), who: item.from }] : [])] }
      : item.who == null
        ? { cls: 'leg', who: name(item.victim), glyph: GLYPH.leg, parts: [{ text: 'DROPS ' }, { text: item.item, kind: 'legn' }] }
        : { cls: 'leg', who, glyph: GLYPH.leg, parts: [{ text: 'KO ' }, { text: name(item.victim), who: item.victim }, { text: ', who DROPS ' }, { text: item.item, kind: 'legn' }] };
    case 'pred': return { cls: 'pred', who, glyph: GLYPH.pred, parts: [{ text: 'PREDICTS ' + kos(item.level) }] };
    case 'res': return { cls: 'res', who, glyph: GLYPH.res, parts: [{ text: 'MADE ' + kos(item.level) + ': correct' }] };
    case 'escape': return { cls: 'escape', who, glyph: GLYPH.escape, parts: [{ text: 'ESCAPES at ' + item.hp + ' HP' }] };
    default: return null;
  }
}

export class Feed {
  // name(id) -> name; colour(id) -> CSS colour of that fighter's name
  constructor(doc, root, { name, colour, dev = () => false }) {
    this.doc = doc; this.name = name; this.colour = colour; this.dev = dev; this.items = []; this.narrow = false; this.seq = 0;
    this.box = doc.createElement('div'); this.box.className = 'b2-slips'; this.box.dataset.panel = 'feed';
    this.list = doc.createElement('ul'); this.list.className = 'feed slipfeed';
    this.list.setAttribute('role', 'log'); this.list.setAttribute('aria-label', 'Arena feed: who said what, KOs, predictions and legendaries');
    // the house's autopilot (no model key, or its budget stopped) is said once over the feed, not on every house line
    this.chip = doc.createElement('span'); this.chip.className = 'chip'; this.chip.textContent = 'House on autopilot'; this.chip.hidden = true;
    this.box.append(this.chip, this.list); root.appendChild(this.box);
  }
  push(item) {
    if (item.kind === 'say' && item.status === 'autopilot') { item = { ...item, status: null, autopilot: true }; }
    this.items.push({ ...item, seq: ++this.seq }); if (this.items.length > 24) this.items.splice(0, this.items.length - 24); this.render(); }
  // a KO line becomes a legendary line when the item it knocked loose is a legendary (one slip per KO)
  upgradeKo(victim, item) {
    for (let i = this.items.length - 1; i >= 0; i--) {
      const it = this.items[i];
      if (it.kind === 'ko' && it.victim === victim) { this.items[i] = { ...it, kind: 'leg', item }; this.render(); return true; }
    }
    return false;
  }
  devChip() { const c = this.doc.createElement('span'); c.className = 'dev'; c.textContent = 'DEV'; return c; }
  setNarrow(narrow) { if (narrow !== this.narrow) { this.narrow = narrow; this.box.dataset.reserve = narrow ? String(PHONE_MAX) : ''; this.render(); } }
  shown() { return this.items.slice(-(this.narrow ? LINES.narrow : LINES.wide)); }
  render() {
    const d = this.doc;
    this.chip.hidden = !this.shown().some((it) => it.autopilot);
    this.list.replaceChildren(...this.shown().map((item) => {
      const s = slip(item, this.name), li = d.createElement('li');
      if (!s) return li;
      li.className = s.cls; li.dataset.kind = item.kind; if (item.who != null) li.dataset.fighterId = item.who; if (item.feedId != null) li.dataset.feedId = String(item.feedId);
      if (item.moment || item.ambush) li.dataset.moment = item.moment || 'ambush';   // a big moment (moments.mjs)
      const whoId = item.who == null && (item.kind === 'ko' || item.kind === 'leg') ? item.victim : item.who;
      const who = d.createElement('b'); who.className = 'who'; who.textContent = s.who; who.style.color = this.colour(whoId); li.appendChild(who);
      if (this.dev(whoId)) li.appendChild(this.devChip());
      if (s.emoji) { const e = d.createElement('span'); e.className = 'emo'; e.textContent = s.emoji; li.appendChild(e); }
      if (s.glyph) { const g = d.createElement('span'); g.className = 'gl ' + s.cls; g.textContent = s.glyph; g.setAttribute('aria-hidden', 'true'); li.appendChild(g); }
      const line = d.createElement('span'); line.className = 'line';
      for (const p of s.parts) {
        if (p.who != null) { const b = d.createElement('b'); b.textContent = p.text; b.style.color = this.colour(p.who); line.appendChild(b); if (this.dev(p.who)) line.appendChild(this.devChip()); }
        else if (p.kind) { const b = d.createElement(p.kind === 'status' ? 'span' : 'b'); b.className = p.kind; b.textContent = p.text; line.appendChild(b); }
        else if (item.kind === 'say') { const dialogue = d.createElement('em'); dialogue.textContent = p.text; line.appendChild(dialogue); }
        else line.appendChild(d.createTextNode(p.text));
      }
      li.appendChild(line);
      return li;
    }));
    // a phone: the box stays within PHONE_MAX; the oldest slips drop out whole until it fits (the newest always shows)
    if (this.narrow) while (this.list.children.length > 1 && this.box.offsetHeight > PHONE_MAX) this.list.removeChild(this.list.firstChild);
  }
}
