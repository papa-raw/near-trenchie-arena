// The pre-jump (Pat's item 51: "the prediction animates before the trenchie jumps into the arena"; approved board 2,
// state "prejump"): the card "<name> predicts N+ KOs" stamps above the drop point (0.25 s), then shrinks into the landing
// spot as the trenchie falls (1.2 s), and the tag lands with N empty circles. The body's drop waits for the stamp
// (DROP_DELAY_MS, actors.onRespawn). Client-side only; the sim never waits on it.
import { circlesModel, circlesNode } from './pips.mjs';

export const STAMP_MS = 250, SHRINK_MS = 1200, DROP_DELAY_MS = STAMP_MS, TOTAL_MS = STAMP_MS + SHRINK_MS;
export const LIFT_PX = 90;   // the card's start, above the drop point

// The card's pose at t ms after the start. from: the drop point on screen; to: where the tag lands. -> {x, y, scale, opacity}
export function pose(t, from, to) {
  if (t < 0) return null;
  if (t < STAMP_MS) { const k = t / STAMP_MS; return { x: from.x, y: from.y - LIFT_PX, scale: 1.4 - 0.4 * k, opacity: k }; }
  const k = Math.min(1, (t - STAMP_MS) / SHRINK_MS), e = k * k * (3 - 2 * k);
  return { x: from.x + (to.x - from.x) * e, y: from.y - LIFT_PX + (to.y - from.y + LIFT_PX) * e, scale: 1 - 0.6 * e, opacity: k < 0.75 ? 1 : 1 - (k - 0.75) / 0.25 };
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
    el.style.opacity = '0'; this.root.appendChild(el);
    this.on.set(id, { el, at: nowMs, w: 0, h: 0 }); return true;
  }
  stop(id) { const p = this.on.get(id); if (p) { p.el.remove(); this.on.delete(id); } }
  /** True while the card is in the air: the fighter's tag waits for it. */
  active(id, nowMs) { const p = this.on.get(id); return !!p && nowMs - p.at < TOTAL_MS; }
  // each frame: from(id) -> the drop point on screen, to(id) -> the tag's landing spot; null skips the fighter
  frame(nowMs, from, to) {
    for (const [id, p] of this.on) {
      const t = nowMs - p.at;
      if (t >= TOTAL_MS) { this.stop(id); continue; }
      const a = from(id), b = to(id) || a; if (!a) continue;
      const q = pose(t, a, b); if (!q) continue;
      if (!p.w) { p.w = p.el.offsetWidth; p.h = p.el.offsetHeight; }
      p.el.style.transform = 'translate(' + (q.x - p.w / 2).toFixed(1) + 'px,' + (q.y - p.h / 2).toFixed(1) + 'px) scale(' + q.scale.toFixed(3) + ')';
      p.el.style.opacity = q.opacity.toFixed(3);
    }
  }
}
