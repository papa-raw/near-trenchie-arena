// The spectator socket's social frame (snap_local.social_frame): checked player personas, the guarded public feed, each
// fighter's current life (its predicted level and KOs, lives.mjs) and the names of every trenchie the host registered.
// Speech goes to the one merged feed (feed.mjs) as tag + emoji + line; no emoji is drawn over a head (Pat, Q4: "the emoji
// stays in the feed line next to the speaker's name"). Presentation data only; it never enters the tick buffer.

/** A feed row as a feed item. A muted or blocked line says so after the line (gate 6: no silent fallback). */
export function sayItem(row) {
  const status = row.muted ? row.label || 'guard list missing' : row.blocked ? 'blocked line' + (row.label ? ' · ' + row.label : '') : row.label || null;
  return { kind: 'say', who: row.who, emoji: row.emoji || null, text: row.text, status, feedId: row.id };
}

export class Social {
  // onSay(item): a new spoken line; onLives(map | null): each frame's lives map (null when the socket closes)
  constructor(KITS, { onSay = () => {}, onLives = () => {} } = {}) {
    this.KITS = KITS; this.onSay = onSay; this.onLives = onLives; this.seen = new Set(); this.names = {};
  }
  apply(value) {
    if (value === null) { this.KITS.players = []; this.seen.clear(); this.onLives(null); return; }
    if (value.version !== 1 || !Array.isArray(value.players) || !Array.isArray(value.feed)) throw new Error('Unsupported arena social metadata');
    this.KITS.players = value.players;
    if (value.names && typeof value.names === 'object') Object.assign(this.names, value.names);   // one object: the HUD holds it
    for (const row of value.feed) if (!this.seen.has(row.id)) { this.seen.add(row.id); this.onSay(sayItem(row)); }
    if (this.seen.size > 512) this.seen = new Set(value.feed.map((r) => r.id));
    if (value.lives !== undefined) this.onLives(value.lives);
  }
}
