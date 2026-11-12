// Layout helpers for the fixed HUD. Pure, so the rule is tested without a browser.
const hit = (a, b, gap = 0) => a.x < b.x + b.w + gap && a.x + a.w + gap > b.x && a.y < b.y + b.h + gap && a.y + a.h + gap > b.y;

/** The lead banner clears every card (as at ebb97a0): its natural place, else right of what it touches, else below all. */
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
