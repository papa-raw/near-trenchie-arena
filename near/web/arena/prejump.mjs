// Pre-jump presentation is a stationary 300ms fade; no stamp, scale change, travel or landing pop.
import { circlesModel, circlesNode } from './pips.mjs';

export const FADE_MS = 300, DROP_DELAY_MS = FADE_MS, TOTAL_MS = FADE_MS;

/** A stationary opacity fade, with a constant scale for callers that inspect the pose. */
export function pose(t, from) {
  if (t < 0) return null;
  return { x: from.x, y: from.y, scale: 1, opacity: Math.max(0, 1 - t / FADE_MS) };
}

export class Prejump {
  constructor(doc, root) { this.doc = doc; this.root = root; this.on = new Map(); }
  /** Start the card for fighter `id` (name, level) at the page time `nowMs`. */
  start(id, name, level, nowMs) {
    const m = circlesModel(level, 0); if (!m) return false;
    this.stop(id);
    const el = this.doc.createElement('div'); el.className = 'pjcard'; el.dataset.fighterId = id;
    const who = this.doc.createElement('b'); who.textContent = name;
    const lv = this.doc.createElement('b'); lv.textContent = level + '+ KO' + (level === 1 ? '' : 's');
    el.append(who, this.doc.createTextNode(' predicts '), lv, circlesNode(this.doc, m, 'big'));
    el.style.opacity = '1'; this.root.appendChild(el);
    this.on.set(id, { el, at: nowMs, w: 0, h: 0 }); return true;
  }
  stop(id) { const p = this.on.get(id); if (p) { p.el.remove(); this.on.delete(id); } }
  /** True during the fade: the fighter's tag waits for it. */
  active(id, nowMs) { const p = this.on.get(id); return !!p && nowMs - p.at < TOTAL_MS; }
  // Each frame: capture the starting point once, then change only opacity.
  frame(nowMs, from) {
    for (const [id, p] of this.on) {
      const t = nowMs - p.at;
      if (t >= TOTAL_MS) { this.stop(id); continue; }
      if (!p.anchor) p.anchor = from(id); if (!p.anchor) continue;
      const q = pose(t, p.anchor); if (!q) continue;
      if (!p.w) { p.w = p.el.offsetWidth; p.h = p.el.offsetHeight; }
      p.el.style.transform = 'translate(' + (q.x - p.w / 2).toFixed(1) + 'px,' + (q.y - p.h / 2).toFixed(1) + 'px)';
      p.el.style.opacity = q.opacity.toFixed(3);
    }
  }
}
