// Where the fixed HUD goes beside board 1's panel (builder-c's contract). Pure, so the board-2 case runs it in node.

// Board 1's panel (builder-c): open, its sign carries data-arena-panel; closed, its tab (desktop) or pill (phone) and
// the latest line's toast sit on the right edge or the bottom. The HUD keeps clear of all of them.
export function panelBoxes(doc) {
  const out = { open: null, closed: [] }, box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 ? { x: r.left, y: r.top, w: r.width, h: r.height } : null; };
  out.open = box(doc.querySelector('[data-arena-panel]'));
  for (const sel of ['#b1-panel .edge-tab', '#b1-panel .pill', '#b1-panel .toast']) { const b = box(doc.querySelector(sel)); if (b) out.closed.push(b); }
  return out;
}

// Where the corner buttons go and how much width the sign has. view {w, h}; panels from panelBoxes; corner {w, h}.
// Desktop: the buttons sit left of an open panel (16 px gap), the sign centres in the free width (the panel's left edge
// less that gap: at 1440 a 460 px panel leaves 952, the sheet's number) and the picture pans so the ring stays in it (pan); a closed tab only
// moves the buttons if they would touch it. Phone: the buttons sit just above an open sheet or above the closed pill.
export function hudLayout(view, panels, corner) {
  const phone = view.w <= 600, m = phone ? 8 : 16;
  let right = m, bottom = phone ? 12 : 16, free = view.w, feedHidden = false, pan = 0;
  const open = panels.open;
  if (open && !phone) { right = view.w - open.x + 16; free = open.x - 16; pan = Math.round((view.w - free) / 2); }
  else if (open && phone) { bottom = view.h - open.y + 8; feedHidden = true; }
  const clash = (b) => { const x = view.w - right - corner.w, y = view.h - bottom - corner.h; return x < b.x + b.w + 6 && x + corner.w > b.x - 6 && y < b.y + b.h + 6 && y + corner.h > b.y - 6; };
  for (const b of panels.closed) if (clash(b)) bottom = Math.max(bottom, view.h - b.y + 8);
  return { right, bottom, free, feedHidden, phone, pan };
}
