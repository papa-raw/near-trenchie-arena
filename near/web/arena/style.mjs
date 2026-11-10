// The five public style words. A spectator never infers a hidden style from a fighter's actions.
const WORDS = Object.freeze({ brawler: 'Brawler', hunter: 'Hunter', looter: 'Looter', guardian: 'Guardian', survivor: 'Survivor' });
export function styleWord(style) { return WORDS[style] || ''; }
export function hasBounty(fighter, items) {
  return fighter.status === 0 && Object.values(fighter.items).some((id) => {
    const it = items[id]; return it && it.tier === 'legendary' && /^house:/.test(it.origin || '') && it.origin !== 'house:' + fighter.id;
  });
}

/** A full map on connect, then atomic deltas from the server. Unknown versions/styles never reach the UI. */
export class StyleState {
  constructor() { this.map = new Map(); this.revision = -1; }
  apply(message) {
    if (!message || message.type !== 'spectator_styles') return false;
    if (message.version !== 1 || !Number.isSafeInteger(message.revision) || message.revision < 0 || typeof message.full !== 'boolean' || !message.styles || typeof message.styles !== 'object' || Array.isArray(message.styles)) throw new Error('Unsupported spectator styles message');
    if (!message.full && message.revision !== this.revision + 1) throw new Error('Style revision gap; reconnect for a full map');
    const next = message.full ? new Map() : new Map(this.map);
    for (const [name, style] of Object.entries(message.styles)) {
      if (!name || (style !== null && !styleWord(style))) throw new Error('Invalid spectator style for ' + name);
      if (style === null) next.delete(name); else next.set(name, style);
    }
    this.map = next; this.revision = message.revision; return true;
  }
}
