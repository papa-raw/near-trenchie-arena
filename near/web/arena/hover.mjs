// The quirk body stays near its own pill. Other tags are hard obstacles; a card permits at most 32 square pixels of contact.
export const MAX_QUIRK_DISTANCE = 240; // Centre-to-centre CSS pixels, checked for every house tag in the viewport cases.
const area = (a, b) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
export function placeQuirkPanel(anchor, size, tags, width, height, cards = []) {
  const margin = 8, gap = 6, w = Math.min(size.w, width - 2 * margin), h = Math.min(size.h, height - 2 * margin);
  const xs = new Set([margin, width - w - margin, anchor.x + (anchor.w - w) / 2, anchor.x, anchor.x + anchor.w - w]);
  const ys = new Set([margin, height - h - margin, anchor.y + anchor.h + gap, anchor.y - h - gap, anchor.y + (anchor.h - h) / 2]);
  for (const rect of [...tags, ...cards]) { xs.add(rect.x - w - gap); xs.add(rect.x + rect.w + gap); ys.add(rect.y - h - gap); ys.add(rect.y + rect.h + gap); }
  const candidates = [];
  for (const x of xs) for (const y of ys) {
    const box = { x: Math.max(margin, Math.min(width - w - margin, x)), y: Math.max(margin, Math.min(height - h - margin, y)), w, h };
    const tagOverlap = tags.reduce((total, tag) => total + area(box, tag), 0), cardOverlap = cards.reduce((total, card) => total + area(box, card), 0);
    const distance = Math.hypot(box.x + w / 2 - anchor.x - anchor.w / 2, box.y + h / 2 - anchor.y - anchor.h / 2);
    candidates.push({ box, tagOverlap, cardOverlap, distance });
  }
  const clear = candidates.filter((c) => c.tagOverlap === 0), acceptable = clear.filter((c) => c.cardOverlap <= 32);
  // Rank distance first once overlap is acceptable; a distant zero-overlap point can never beat a nearby acceptable one.
  const pool = acceptable.length ? acceptable : clear.length ? clear : candidates;
  pool.sort((a, b) => a.distance - b.distance || a.tagOverlap - b.tagOverlap || a.cardOverlap - b.cardOverlap);
  return pool[0].box;
}
