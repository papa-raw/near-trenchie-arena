// Prediction circles by a name tag, and the crowd card (approved board 2, direction C, "Wall sign"; Pat's item 51:
// "tiny circles by the name tag that start empty and fill green as it meets its prediction").
// One circle per predicted KO, filled green per KO this life, ringed green when met, "+N" for KOs beyond.
// Three or more fighters within reach of each other share one card ("N here", each name with its circles, left to right),
// placed where it covers the fewest other fighters (above, right, left, below), never under the sign or off screen.
// Pure functions: the DOM is built by circlesNode, and the arena-board2 case tests the rest in node.

// The circles a tag shows. level: the life's predicted level (1-4) or null (no circles); kos: KOs this life.
export function circlesModel(level, kos) {
  if (!Number.isInteger(level) || level < 1) return null;
  const k = Math.max(0, kos | 0);
  return { n: level, filled: Math.min(k, level), met: k >= level, extra: Math.max(0, k - level) };
}

// The words a screen reader gets for the circles (the sheet's aria-label).
export function circlesLabel(m) { return m ? 'predicts ' + m.n + '+ KOs, ' + (m.filled + m.extra) + ' so far' : ''; }

export function circlesNode(doc, m, cls = '') {
  const s = doc.createElement('span');
  s.className = 'pips' + (m.met ? ' met' : '') + (cls ? ' ' + cls : '');
  s.setAttribute('role', 'img'); s.setAttribute('aria-label', circlesLabel(m));
  for (let i = 0; i < m.n; i++) { const c = doc.createElement('i'); if (i < m.filled) c.className = 'on'; s.appendChild(c); }
  if (m.extra) { const b = doc.createElement('b'); b.textContent = '+' + m.extra; s.appendChild(b); }
  return s;
}
// a stable key for a model, so a tag's circles are rebuilt only when they change
export const circlesKey = (m) => (m ? m.n + ':' + m.filled + ':' + m.extra : '');

// Within reach: the sheet's numbers, 110 x 60 px at 1440 and 70 x 34 px at 390, between tag anchors.
export const REACH = { wide: { rx: 110, ry: 60 }, narrow: { rx: 70, ry: 34 } };
export const reachFor = (w) => (w < 600 ? REACH.narrow : REACH.wide);

// Groups of three or more fighters chained within reach. items: [{id, x, y}] (tag anchors, screen px). Returns arrays
// of ids, each sorted left to right; a fighter with fewer than two others in reach keeps its own tag.
export function crowdGroups(items, reach) {
  const near = (a, b) => Math.abs(a.x - b.x) < reach.rx && Math.abs(a.y - b.y) < reach.ry;
  const seen = new Set(), groups = [];
  for (const f of items) {
    if (seen.has(f.id) || !items.some((o) => o !== f && near(o, f))) continue;
    const g = [f]; seen.add(f.id);
    for (let i = 0; i < g.length; i++) for (const o of items) if (!seen.has(o.id) && near(o, g[i])) { g.push(o); seen.add(o.id); }
    if (g.length > 2) groups.push(g.sort((a, b) => a.x - b.x || (a.id < b.id ? -1 : 1)).map((o) => o.id));
    else for (const o of g) seen.delete(o.id);
  }
  return groups;
}

// Where a group's card goes. members/others: [{id, x, y}]; card {w, h}; view {w, h, top (the sign's bottom), bottom
// (the lowest y a card may reach: above the feed and the buttons)}. Candidates as the sheet draws them: above the group,
// right of it, left of it, below it; each scores 2 per other fighter it covers plus 5 if it leaves the screen, runs past
// the bottom limit, or reaches under the sign. Lowest score wins; ties keep the sheet's order. Returns {pos, x, y, box}:
// (x, y) is the card's anchor (its pointer), box its rect.
export function cardSpot(members, others, card, view) {
  const xs = members.map((f) => f.x), ys = members.map((f) => f.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const cx = xs.reduce((a, b) => a + b, 0) / xs.length, midY = (minY + maxY) / 2 + 30, { w, h } = card;
  const cands = [
    { pos: 'up', x: cx, y: minY - 12, box: { x: cx - w / 2, y: minY - 12 - h, w, h } },
    { pos: 'right', x: maxX + 50, y: midY, box: { x: maxX + 50, y: midY - h / 2, w, h } },
    { pos: 'left', x: minX - 50, y: midY, box: { x: minX - 50 - w, y: midY - h / 2, w, h } },
    { pos: 'below', x: cx, y: maxY + 90, box: { x: cx - w / 2, y: maxY + 90, w, h } },
  ];
  let best = null, bestScore = Infinity;
  for (const c of cands) {
    const b = c.box;
    const hit = others.filter((o) => o.x > b.x - 40 && o.x < b.x + b.w + 40 && o.y + 60 > b.y && o.y - 10 < b.y + b.h).length;
    const off = (b.x < 8 || b.x + b.w > view.w - 8 || b.y + b.h > view.bottom || b.y < 8 ? 5 : 0) + (b.y < view.top ? 5 : 0);
    const score = hit * 2 + off;
    if (score < bestScore) { best = c; bestScore = score; }
  }
  return best;
}
