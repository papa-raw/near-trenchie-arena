// Name tags in a crowd (tight crowds overlapped into unreadable text). B2 a v3.1's tag
// vocabulary only: the same small tag, moved a row up or half a tag aside, or faded out. No leader lines, no new chrome.
// Order: the must-win tags (your fighter, its focus target, the current speaker) first, then the KO leader and bounty
// holders, then everyone else nearest the camera first. Within a tier the tag shown longest goes first and tries its
// previous slot first, so a tag that just appeared never pushes out one that was already there: tags do not swap or
// flicker as a crowd shuffles. A hidden tag comes back only after its place has been free for SHOW_AFTER frames.
// A tag with no free slot is faded out; no two shown tags overlap, and no shown tag covers an HP bar (obstacles). Pure: no DOM, so the rule is tested in Node.

export const TIER = { must: 0, notable: 1, other: 2 };
const GAP = 1;   // px kept clear between two tags
export const SHOW_AFTER = 8;   // frames a hidden tag's place must stay free before it shows again (~130 ms at 60 Hz)

// slot offsets in units of (tag width, tag row height), relative to the tag's own place just above the head
const SLOTS = [[0, 0], [0, -1], [-0.55, 0], [0.55, 0], [0, -2], [-0.55, -1], [0.55, -1]];
const MUST_SLOTS = SLOTS.concat([[0, -3], [-1.05, 0], [1.05, 0], [-1.05, -1], [1.05, -1], [0, 1]]);

const hits = (a, b) => a.x < b.x + b.w + GAP && a.x + a.w + GAP > b.x && a.y < b.y + b.h + GAP && a.y + a.h + GAP > b.y;

/**
 * items: [{ id, ax, ay, w, h, tier, depth }] where (ax, ay) is the point just above the head (the tag's bottom centre)
 *   and a larger depth is nearer the camera.
 * view: { w, h, pad = 4, prev: Map id -> { shown, slot } from the last frame, obstacles: [{ x, y, w, h }] that no tag may
 *   cover (the HP bars) }
 * returns Map id -> { x, y, w, h, shown, slot, streak } (streak: frames shown in a row, or free-but-waiting frames as a
 *   negative count while hidden)
 */
export function layoutTags(items, { w, h, pad = 4, prev = new Map(), obstacles = [] }) {
  const shownFor = (id) => Math.max(0, prev.get(id)?.streak || 0);
  const order = items.slice().sort((a, b) => (a.tier - b.tier) || (shownFor(b.id) - shownFor(a.id))
    || (b.depth - a.depth) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const placed = [], out = new Map();
  for (const it of order) {
    const slots = it.tier === TIER.must ? MUST_SLOTS : SLOTS, last = prev.get(it.id);
    const tryOrder = last && last.shown && last.slot < slots.length ? [last.slot, ...slots.keys()].filter((s, i, a) => a.indexOf(s) === i) : [...slots.keys()];
    let got = null;
    for (const s of tryOrder) {
      const [dx, dy] = slots[s];
      const x = Math.max(pad, Math.min(w - it.w - pad, it.ax - it.w / 2 + dx * it.w));
      const y = Math.max(pad, Math.min(h - it.h - pad, it.ay - it.h - 2 + dy * (it.h + GAP)));
      const r = { x, y, w: it.w, h: it.h };
      if (!placed.some((p) => hits(r, p)) && !obstacles.some((p) => hits(r, p))) { got = { ...r, slot: s }; break; }
    }
    if (!got && it.tier === TIER.must) {
      // every nearby slot is taken. In order: a row or three further up clear of tags and bars; then a nearby slot clear
      // of tags even if it crosses a bar (near its fighter beats far); then further up; at home only if all are full.
      const at = (dx, k) => ({ x: Math.max(pad, Math.min(w - it.w - pad, it.ax - it.w / 2 + dx * it.w)),
        y: Math.max(pad, Math.min(h - it.h - pad, it.ay - it.h - 2 + k * (it.h + GAP))), w: it.w, h: it.h });
      const clear = (r, bars) => !placed.some((p) => hits(r, p)) && (!bars || !obstacles.some((p) => hits(r, p)));
      const tries = [[-4, -5, -6].map((k) => [at(0, k), true]), MUST_SLOTS.map(([dx, dy]) => [at(dx, dy), false]),
        [-7, -8, -9, -10, 2, 3, 4, 5, 6].map((k) => [at(0, k), false])].flat();
      const hit = tries.find(([r, bars]) => clear(r, bars));
      got = { ...(hit ? hit[0] : at(0, 0)), slot: 0 };
    }
    const was = prev.get(it.id), wasShown = !!(was && was.shown), waited = was && !was.shown ? -(was.streak || 0) : 0;
    if (got && it.tier !== TIER.must && !wasShown && prev.size && waited + 1 < SHOW_AFTER) {
      // free now, but only just: wait a few frames before showing, so a tag does not blink in a gap that closes again
      out.set(it.id, { ...got, shown: false, streak: -(waited + 1) });
    } else if (got) { placed.push(got); out.set(it.id, { ...got, shown: true, streak: wasShown ? (was.streak || 0) + 1 : 1 }); }
    else out.set(it.id, { x: Math.max(pad, Math.min(w - it.w - pad, it.ax - it.w / 2)), y: Math.max(pad, it.ay - it.h - 2), w: it.w, h: it.h, shown: false, slot: 0, streak: 0 });
  }
  return out;
}
