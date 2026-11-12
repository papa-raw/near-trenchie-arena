// Where the fixed HUD goes beside board 1's panel, by that panel's contract. Pure, so the board-2 case runs it in node.

// Board 1's panel: open, its sign carries data-arena-panel; closed, its tab (desktop) or pill (phone) and
// the latest line's toast sit on the right edge or the bottom. The HUD keeps clear of all of them.
export function panelBoxes(doc) {
  const out = { open: null, closed: [] }, box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 ? { x: r.left, y: r.top, w: r.width, h: r.height } : null; };
  out.open = box(doc.querySelector('[data-arena-panel]'));
  for (const sel of ['#b1-panel .edge-tab', '#b1-panel .pill', '#b1-panel .toast']) { const b = box(doc.querySelector(sel)); if (b) out.closed.push(b); }
  return out;
}

// A phone (<= 600 px) with board 1's panel open: the arena draws only above the panel (h = the panel's top), and the ring is
// framed below the sign (top = the sign's bottom). null otherwise, or before either is on screen.
export function phoneStrip(doc, w, h) {
  if (w > 600) return null;
  const open = panelBoxes(doc).open, sign = doc.querySelector('#world [data-panel="board"]');
  if (!open || open.y < 120 || open.y >= h) return null;
  const s = sign ? sign.getBoundingClientRect() : null, top = s && s.height > 0 && s.bottom < open.y - 60 ? Math.round(s.bottom) : 0;
  return { h: Math.round(open.y), top };
}

// Where the corner buttons go and how much width the sign has. view {w, h}; panels from panelBoxes; corner {w, h}.
// Desktop: the buttons sit left of an open panel (16 px gap), the sign centres in the free width (the panel's left edge
// less that gap: at 1440 a 460 px panel leaves 952, the sheet's number) and the picture pans so the ring stays in it (pan); a closed tab only
// moves the buttons if they would touch it. Phone: the buttons sit just above the closed pill; with the sheet open
// they turn compact (two 40 px round buttons, their words in their labels) and sit just above the sheet's top edge,
// right-aligned, in the strip under the plank (agreed with board 1: the sheet never rises above y 290 at <= 600 px), so
// they never cover a board.
export const COMPACT = { w: 2 * 40 + 8, h: 40 };
export function hudLayout(view, panels, corner) {
  const phone = view.w <= 600, m = phone ? 8 : 16;
  let right = m, bottom = phone ? 12 : 16, free = view.w, feedHidden = false, pan = 0;
  const open = panels.open;
  if (open && !phone) { right = view.w - open.x + 16; free = open.x - 16; pan = Math.round((view.w - free) / 2); }
  let compact = false;
  if (open && phone) { bottom = view.h - open.y + 8; feedHidden = true; compact = true; corner = COMPACT; }
  const clash = (b) => { const x = view.w - right - corner.w, y = view.h - bottom - corner.h; return x < b.x + b.w + 6 && x + corner.w > b.x - 6 && y < b.y + b.h + 6 && y + corner.h > b.y - 6; };
  for (const b of panels.closed) if (clash(b)) bottom = Math.max(bottom, view.h - b.y + 8);
  return { right, bottom, free, feedHidden, phone, pan, compact, corner };
}

/** The compact buttons (phone, sheet open) hide only if they would reach the plank (a sheet risen past its contract):
 *  L from hudLayout; view {h}; plank the wall sign's rect. Their top must stay at least 6 px under the plank. */
export function cornerHidden(L, view, plank) {
  if (!L.compact || !plank) return false;
  return view.h - L.bottom - L.corner.h < plank.y + plank.h + 6;
}
