// Picking a body from a click (F19): the nearest projected body centre inside a radius. Pure, so it is tested without a browser.
export const PICK_PX = 46;           // how close to a body's centre a click must land
// the nearest on-screen body to a click, or null; `screenOf(id)` gives the projected centre
export function pickFighter(ids, screenOf, x, y, maxPx = PICK_PX) {
  let best = null, bd = maxPx * maxPx;
  for (const id of ids) { const s = screenOf(id); if (!s) continue; const d = (s.x - x) ** 2 + (s.y - y) ** 2; if (d < bd) { bd = d; best = id; } }
  return best;
}

