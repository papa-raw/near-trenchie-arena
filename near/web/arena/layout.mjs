// Layout helpers for the fixed HUD. Pure, so the rule is tested without a browser.
const hit = (a, b, gap = 0) => a.x < b.x + b.w + gap && a.x + a.w + gap > b.x && a.y < b.y + b.h + gap && a.y + a.h + gap > b.y;

/** Keep the replay-only pill above the feed when their natural phone positions intersect. */
export function placeReplayStatus(natural, feed, width, height) {
  const margin = 8, box = { ...natural, x: Math.max(margin, Math.min(width - natural.w - margin, natural.x)) };
  if (feed && hit(box, feed, margin)) box.y = Math.max(margin, feed.y - box.h - margin);
  box.y = Math.min(height - box.h - margin, box.y); return box;
}
