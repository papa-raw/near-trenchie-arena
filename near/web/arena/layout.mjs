// Where the lead banner goes: clear of every card. Pure, so the rule is tested at 1440 and 390 without a browser.
//   N = the banner's natural rect {x, y, w, h} from the panel art; cards = [{x, y, w, h}] (the House card, the Players card, their labels)
// If the banner at its natural place touches no card, it stays. Otherwise it moves right of the cards it touches, if it fits on screen
// and touches nothing there; otherwise it goes below every card.
const hit = (a, b, gap = 0) => a.x < b.x + b.w + gap && a.x + a.w + gap > b.x && a.y < b.y + b.h + gap && a.y + a.h + gap > b.y;

export function placeBanner(N, cards, W, margin = 12) {
  if (!N) return null;
  const at = (x, y) => ({ x, y, w: N.w, h: N.h });
  if (!cards.some((c) => hit(at(N.x, N.y), c, 4))) return { x: N.x, y: N.y, how: 'natural' };
  const touched = cards.filter((c) => hit(at(N.x, N.y), c, 4));
  const right = Math.max(...touched.map((c) => c.x + c.w)) + 8;
  if (right + N.w <= W - margin && !cards.some((c) => hit(at(right, N.y), c, 4))) return { x: right, y: N.y, how: 'right' };
  const bottom = Math.max(...cards.map((c) => c.y + c.h)) + 6;
  return { x: Math.min(N.x, Math.max(margin, W - margin - N.w)), y: bottom, how: 'below' };
}


/** Keep the replay-only pill above the feed when their natural phone positions intersect. */
export function placeReplayStatus(natural, feed, width, height) {
  const margin = 8, box = { ...natural, x: Math.max(margin, Math.min(width - natural.w - margin, natural.x)) };
  if (feed && hit(box, feed, margin)) box.y = Math.max(margin, feed.y - box.h - margin);
  box.y = Math.min(height - box.h - margin, box.y); return box;
}
