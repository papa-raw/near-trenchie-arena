// Big moments for the ticker (Battle mode, Pat 2026-11-11: "the ticker also announces big moments").
// The frozen B2 a ticker art already draws a KO (▼) and a legendary landing in a hand (◆ FILL); these are the moments it
// has no line for: a legendary hitting the sand, a legendary stolen, a near-death escape, an ambush KO. Each is worked
// out here from the same snapshot events and fighter states the view already has. No model call, no new state on the
// server: presentation only, never in the tick buffer.

export const NEAR_DEATH_PCT = 10;      // at or below this share of its max HP a fighter is near death
export const ESCAPE_TICKS = 60;        // ...and escapes when it is still standing 3 s (60 ticks) later
export const GLYPH = { legendary_drop: '◆', legendary_steal: '◆', near_death: '✚', ambush: '▼' };

// A legendary is stolen when it lands in a hand that is not its owner's (the same test main.mjs uses for slow-mo).
export const isSteal = (item, grabber) => !!item && item.tier === 'legendary' && item.origin !== 'house:' + grabber;

export class Moments {
  constructor(ITEMS, tagOf) {
    this.ITEMS = ITEMS; this.tagOf = tagOf;
    this.hpMax = new Map();      // fighter -> highest HP seen this life (the view's own hpMax rule)
    this.low = new Map();        // fighter -> tick it fell to near death this life
    this.escaped = new Set();    // fighters that already escaped this life (one line a life)
    this.lastKo = null;          // {fighter, tick, items}: who a legendary on the sand came from
    this.seenDrops = new Set();
    this.prev = null;            // the previous snapshot, for targets at the moment of a KO
  }

  // One event as the view fires it. Returns the moments it makes (0 or 1).
  onEvent(ev, snap) {
    if (ev.kind === 'ko') {
      const victim = (this.prev || snap).fighters.find((f) => f.id === ev.fighter);
      this.lastKo = { fighter: ev.fighter, tick: snap.tick, items: victim ? Object.values(victim.items || {}) : [] };
      this.low.delete(ev.fighter); this.escaped.delete(ev.fighter); this.hpMax.delete(ev.fighter);
      // an ambush: the victim was busy with someone else when its killer struck
      if (ev.source && victim && victim.target && victim.target !== ev.source)
        return [this.line('ambush', ev.source, ev.fighter, null, snap.tick)];
      return [];
    }
    if (ev.kind === 'respawn') { this.low.delete(ev.fighter); this.escaped.delete(ev.fighter); this.hpMax.delete(ev.fighter); return []; }
    if (ev.kind === 'grab' && !ev.destroyed) {
      const item = this.ITEMS[ev.row];
      if (isSteal(item, ev.fighter)) {
        const owner = String(item.origin || '').startsWith('house:') ? item.origin.slice(6) : null;
        return [this.line('legendary_steal', ev.fighter, owner, item.name, snap.tick)];
      }
    }
    return [];
  }

  // Each newer snapshot: legendaries newly on the sand, and near-death falls and escapes.
  onSnapshot(snap) {
    const out = [];
    for (const d of snap.drops || []) {
      if (this.seenDrops.has(d.key)) continue;
      this.seenDrops.add(d.key);
      const item = this.ITEMS[d.item];
      if (!item || item.tier !== 'legendary') continue;
      const from = this.lastKo && snap.tick - this.lastKo.tick <= 40 && this.lastKo.items.includes(d.item) ? this.lastKo.fighter : null;
      out.push(this.line('legendary_drop', from, null, item.name, snap.tick));
    }
    for (const f of snap.fighters) {
      if (f.status !== 0) continue;
      const max = Math.max(this.hpMax.get(f.id) || 0, f.hp); this.hpMax.set(f.id, max);
      if (max <= 0) continue;
      const pct = (100 * f.hp) / max;
      if (!this.low.has(f.id) && !this.escaped.has(f.id) && f.hp > 0 && pct <= NEAR_DEATH_PCT) this.low.set(f.id, snap.tick);
      const since = this.low.get(f.id);
      if (since !== undefined && snap.tick - since >= ESCAPE_TICKS && f.hp > 0) {
        this.low.delete(f.id); this.escaped.add(f.id);
        out.push(this.line('near_death', f.id, null, null, snap.tick, f.hp));
      }
    }
    this.prev = snap;
    return out;
  }

  line(kind, fighter, other, item, tick, hp) {
    const a = fighter ? this.tagOf(fighter) : null, b = other ? this.tagOf(other) : null;
    const text = kind === 'ambush' ? 'AMBUSHES ' + b
      : kind === 'legendary_steal' ? 'STEALS ' + item + (b ? ' from ' + b : '')
      : kind === 'legendary_drop' ? (a ? 'DROPS ' : '') + item + (a ? '' : ' hits the sand')
      : 'ESCAPES at ' + hp + ' HP';
    return { kind, fighter, other, item, tick, tag: a, glyph: GLYPH[kind], text };
  }
}
