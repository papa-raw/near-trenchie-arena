// Bound cast geometry and plain rule text from the existing opt-in spectator metadata channel.
const SIGNATURES = new Set(['beam_sweep', 'blink_strike', 'bubble', 'chain_storm', 'dodge_roll', 'magnet', 'shockwave']);
const integer = (n) => Number.isSafeInteger(n) && n >= 0;
export const castKey = (c) => c.who + ':' + c.resolveAt;
function validCast(key, value) {
  if (!value || typeof value !== 'object') return false;
  return [typeof value.who === 'string', Boolean(value.who), key === castKey(value), integer(value.resolveAt), integer(value.startTick),
    value.startTick <= value.resolveAt, integer(value.radiusMilli), integer(value.arcMillidegrees), value.arcMillidegrees <= 360000,
    SIGNATURES.has(value.signature), ['circle', 'cone'].includes(value.shape), typeof value.item === 'string',
    value.strikeRadiusMilli === undefined || integer(value.strikeRadiusMilli)].every(Boolean);
}
function validateEnvelope(message) {
  const fields = [message.version === 1, integer(message.tick), integer(message.revision), typeof message.full === 'boolean',
    Boolean(message.casts), typeof message.casts === 'object', !Array.isArray(message.casts)];
  if (!fields.every(Boolean)) throw new Error('Unsupported spectator cast metadata');
  if (message.rules) {
    const rules = message.rules;
    if (![typeof rules.version === 'string', Boolean(rules.item_quirks), typeof rules.item_quirks === 'object', !Array.isArray(rules.item_quirks)].every(Boolean)) throw new Error('Invalid spectator quirk rules');
  }
}
export class CastDetails {
  constructor() { this.records = new Map(); this.rules = null; this.revision = -1; this.tick = -1; }
  apply(message) {
    if (!message || message.type !== 'spectator_styles' || !('casts' in message)) return false;
    validateEnvelope(message);
    if (!message.full && message.revision !== this.revision + 1) throw new Error('Cast metadata revision gap');
    const records = message.tick < this.tick ? new Map() : new Map(this.records);
    for (const [key, value] of Object.entries(message.casts)) {
      if (value === null) continue; // Keep a finished cast through the delayed render buffer.
      if (!validCast(key, value)) throw new Error('Invalid bound cast geometry');
      records.set(key, { ...value });
    }
    for (const [key, value] of records) if (value.resolveAt + 120 < message.tick) records.delete(key); // Six seconds beyond the cast covers the spectator buffer.
    const rules = message.rules || this.rules;
    this.records = records; this.rules = rules; this.revision = message.revision; this.tick = message.tick; return true;
  }
  geometry(cast) {
    const record = this.records.get(castKey(cast));
    return record && record.signature === cast.sig ? record : null;
  }
}
export function quirkText(fighter, rules) {
  return [...new Set(Object.values(fighter.items || {}).map((id) => rules?.item_quirks?.[id]?.text).filter((s) => typeof s === 'string' && s))].join(' ');
}
