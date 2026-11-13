// The wall sign (approved board 2, direction C): two boards on one plank hung at the top centre, read from the host's
// public record (GET /house/leaderboards.json, near/arena/predict.py). "Most KOs this hour" (O3) and "Correct predictions
// today (UTC)" (N5), each with a Players | House switch (the house apart from players, O3); both boards switch together.
// Top 3 at 1440; the leader alone on a phone or in a window under 780 px tall. Predictions show the count correct
// ("4 ✓") at every width, so the name is never cut.
// The rows are the host's `boards` (most_kos_hour, most_correct_day, each split into players and house); a host
// without them shows both boards empty ("No KOs yet"), never another window under this label.

export const PERIOD_MS = 10000;
export const WORDS = { ko: 'Most KOs', koWhen: 'this hour', pr: 'Correct predictions', prShort: 'Predictions',
  prWhen: 'today (UTC)', players: 'Players', house: 'House', correct: '✓',
  noKos: 'No KOs yet', noCorrect: 'No correct predictions yet', offline: 'No arena running', counted: 'Counted as each life ends.' };

/** The boards route on the same host as the spectator socket. */
export function signUrl(wsUrl) {
  const u = new URL(wsUrl);
  u.protocol = u.protocol === 'wss:' ? 'https:' : 'http:';
  u.pathname = '/house/leaderboards.json'; u.search = ''; u.hash = '';
  return u.href;
}

/** How many rows a board shows: 3, or 1 on a phone or a short window. */
export const rowsFor = (vw, vh) => (vw <= 600 || vh < 780 ? 1 : 3);

/** The two boards for one side from one leaderboards.json. side: 'players' | 'house'.
 *  -> {ko: {rows:[{id, num}]}, pr: {rows:[{id, num, count}]}} */
export function boards(json, side, n) {
  const b = (json && json.boards) || {};
  // The host ranks before taking its top rows; a row needs a KO or a correct prediction to place.
  const ko = ((b.most_kos_hour && b.most_kos_hour[side]) || []).filter((r) => r.kos > 0), pr = ((b.most_correct_day && b.most_correct_day[side]) || []).filter((r) => r.correct > 0);
  return {
    ko: { rows: ko.slice(0, n).map((r) => ({ id: r.persona, num: r.kos })) },
    pr: { rows: pr.slice(0, n).map((r) => ({ id: r.persona, num: r.correct, count: r.correct })) },
  };
}

// Where the sign hangs. view {w, h}; free: the width left of an open panel. Phone: min(w - 16, 374), centred; desktop:
// min(640, free - 360) centred in the free width (the sheet's numbers).
export function signBox(view, free) {
  if (view.w <= 600) { const w = Math.min(view.w - 16, 374); return { x: (view.w - w) / 2, w }; }
  const w = Math.max(280, Math.min(640, free - 360));
  return { x: Math.max(16, (free - w) / 2), w };
}

const escHtml = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
export const LONG_WORD = 12, HYPHEN_EVERY = 6;
/** A name's markup on the sign. A word longer than LONG_WORD letters gets soft hyphens every HYPHEN_EVERY letters (not
 *  within 3 of either end), so when it must break it shows a hyphen. A DEV chip stays with the name's last word: the
 *  last piece of that word and the chip are one no-break pair, so the chip never stands on a line of its own. */
export function nameHtml(name, dev) {
  const words = String(name).split(/(\s+)/), pieces = (w) => {
    if (w.length <= LONG_WORD) return [w];
    const out = []; let i = 0;
    while (w.length - i > HYPHEN_EVERY + 3) { const cut = Math.max(i + 3, i + HYPHEN_EVERY); out.push(w.slice(i, cut)); i = cut; }
    out.push(w.slice(i)); return out;
  };
  const last = words.length - 1, html = words.map((w, k) => {
    if (/^\s+$/.test(w) || !w) return w ? ' ' : '';
    const p = pieces(w).map(escHtml);
    if (k !== last || !dev) return p.join('&shy;');
    return p.slice(0, -1).map((x) => x + '&shy;').join('') + '<span class="nb">' + p[p.length - 1] + '&nbsp;<span class="dev">DEV</span></span>';
  });
  return html.join('');
}

/** The two columns' markup for boards(...) b. o: {side, short (the short predictions title), offline, name(id), face(id)
 *  -> URL or null, dev(id)}. Pure, so the case reads it without a browser. */
export function columnsHtml(b, o) {
  const W = WORDS, esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  // two toggle buttons, one pressed (both boards switch together)
  const sw = '<span class="sw" role="group" aria-label="Show players or the house">' + ['players', 'house'].map((s) =>
    '<button type="button" data-side="' + s + '" aria-pressed="' + (s === o.side) + '" class="' + (s === o.side ? 'on' : '') + '">' + W[s] + '</button>').join('') + '</span>';
  const face = (id) => { const u = o.face(id); return u ? '<img class="face" src="' + esc(u) + '" alt="">' : '<span class="face" aria-hidden="true"></span>'; };
  const col = (kind) => {
    const head = '<div class="ct"><span class="ttl">' + (kind === 'ko' ? W.ko : (o.short ? W.prShort : W.pr)) + ' <small>' + (kind === 'ko' ? W.koWhen : W.prWhen) + '</small></span>' + sw + '</div>';
    const rows = o.offline ? [] : b[kind].rows;
    const body = rows.length ? rows.map((r, i) => '<li><span class="rk">' + (i + 1) + '</span>' + face(r.id) + '<span class="nm"><span class="t">' + nameHtml(o.name(r.id), o.dev(r.id)) + '</span></span><b class="num">' + r.num +
        (kind === 'pr' ? ' ' + W.correct : '') + '</b></li>').join('')
      : '<li class="empty">' + (o.offline ? W.offline : kind === 'ko' ? W.noKos : W.noCorrect) + '</li>';
    return head + '<ol>' + body + '</ol>';
  };
  return { ko: col('ko'), pr: col('pr') };
}

export class Sign {
  // name(id) -> name; face(id) -> image URL or null (drawn lazily)
  constructor(doc, root, { name, face, dev = () => false }) {
    this.doc = doc; this.name = name; this.face = face; this.dev = dev; this.side = 'players'; this.json = null; this.sig = ''; this.painted = ''; this.offline = false;
    const el = this.el = doc.createElement('div'); el.className = 'wallsign'; el.dataset.panel = 'board';
    el.innerHTML = '<svg class="cords" width="100%" height="30" aria-hidden="true"><path stroke="#6e5236" stroke-width="2.4" stroke-dasharray="4 2" fill="none"/></svg><div class="plank"><div class="col" data-board="ko"></div><div class="col" data-board="pr"></div><p class="counted">' + WORDS.counted + '</p></div>';
    el.addEventListener('click', (e) => { const t = e.target.closest('[data-side]'); if (!t) return; e.preventDefault(); this.setSide(t.dataset.side); });
    root.appendChild(el);
    if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(() => { this.fit(); this.paint(); });   // names measured in their own font
  }
  setSide(side) { if (side !== this.side) { this.side = side; this.sig = ''; this.render(); } }
  setData(json) { this.json = json; this.offline = false; this.render(); }
  // the host's boards could not be read (no arena running, or a restart): say so rather than show an empty board
  setOffline() { if (!this.offline) { this.offline = true; this.render(); } }
  // place and draw; called on resize and when the free width changes (an open panel)
  layout(view, free) {
    const phone = view.w <= 600, box = signBox(view, free), n = rowsFor(view.w, view.h), narrow = box.w < 600;
    const key = [box.x, box.w, phone, n].join('|');
    if (key === this.layoutKey) return;
    this.layoutKey = key; this.n = n; this.phone = phone; this.narrow = narrow;
    this.el.style.left = Math.round(box.x) + 'px'; this.el.style.width = Math.round(box.w) + 'px';
    this.el.classList.toggle('narrow', narrow); this.el.classList.toggle('phone', phone);
    this.el.querySelector('.cords path').setAttribute('d', 'M' + box.w * 0.12 + ' 0L' + box.w * 0.14 + ' 30M' + box.w * 0.88 + ' 0L' + box.w * 0.86 + ' 30');
    this.sig = ''; this.render();
  }
  render() {
    if (this.n == null) return;
    const b = boards(this.json, this.side, this.n);
    // the names are part of the key: a name that arrives after the boards (the social frame) redraws its row
    const names = [...b.ko.rows, ...b.pr.rows].map((r) => this.name(r.id));
    const sig = JSON.stringify([b, names, this.side, this.n, this.narrow, this.phone, this.offline]);
    if (sig === this.sig) return;
    this.sig = sig;
    const html = columnsHtml(b, { side: this.side, short: this.narrow || this.phone, offline: this.offline, name: this.name, face: this.face, dev: this.dev });
    this.el.querySelector('[data-board="ko"]').innerHTML = html.ko;
    this.el.querySelector('[data-board="pr"]').innerHTML = html.pr;
    this.fit(); this.paint();   // the fit changes the plank's height: paint the wood after it
  }
  /** After a draw, the sheet's rule that a name is never cut: if any name would not fit on its line, the rank and the face
   *  drop (tight) and names wrap between words onto at most 2 lines. If a name still needs more,
   *  it takes the row's whole width and the numbers go on the line below (stack). An ellipsis only beyond that (CSS).
   *  Re-run when the fonts arrive. */
  fit() {
    const el = this.el; if (!el.classList || !el.querySelectorAll) return;
    const names = () => [...el.querySelectorAll('.nm .t')];
    el.classList.remove('tight', 'stack');
    if (!names().some((t) => t.scrollWidth > t.clientWidth + 1)) return;
    el.classList.add('tight');
    if (names().some((t) => t.scrollHeight > t.clientHeight + 1 || t.scrollWidth > t.clientWidth + 1)) el.classList.add('stack');
  }
  // the plank's wood (the shared art kit, snapin/art/ska.js), redrawn only when the plank's size changes
  paint() {
    const SKA = globalThis.SKA, plank = this.el.querySelector('.plank'); if (!SKA || !plank) return;
    const r = plank.getBoundingClientRect(), w = Math.round(r.width), h = Math.round(r.height), key = w + 'x' + h;
    if (!w || !h || key === this.painted) return;
    this.painted = key;
    const old = plank.querySelector(':scope > svg.material'); if (old) old.remove();
    plank.insertAdjacentHTML('afterbegin', SKA.svg(w, h, SKA.plank({ x: 0, y: 0, w, h, text: '', color: '#c9966a' }).svg, ' class="material" aria-hidden="true"'));
  }
  rect() { const r = this.el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }
}

/** Polls the boards; a failed poll calls onOffline (the sign says no arena is running) and says so once on the console. */
export class SignFeed {
  constructor(url, onBoards, { fetchFn = (...a) => globalThis.fetch(...a), periodMs = PERIOD_MS } = {}) {
    this.url = url; this.onBoards = onBoards; this.fetchFn = fetchFn; this.periodMs = periodMs; this.timer = null; this.warned = false; this.onOffline = () => {};
  }
  async poll() {
    try {
      const r = await this.fetchFn(this.url, { cache: 'no-store' });
      if (!r.ok) throw new Error('boards ' + r.status);
      this.onBoards(await r.json()); this.warned = false;
    } catch (e) { this.onOffline(); if (!this.warned) { this.warned = true; console.warn('leaderboards unavailable: the sign says no arena is running', String(e)); } }
  }
  start() { this.poll(); this.timer = setInterval(() => this.poll(), this.periodMs); return this; }
  stop() { clearInterval(this.timer); this.timer = null; }
}
