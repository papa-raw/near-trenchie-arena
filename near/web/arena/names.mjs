// Names on screen. A fighter whose id starts with `dev-` is a DEV identity (a developer's own snap-in session, not a player the
// game vouches for): it is labelled DEV wherever it shows, so nobody mistakes it for a house trenchie or a real player (gate 6).
export const DEV_PREFIX = 'dev-';
export const isDev = (id) => typeof id === 'string' && id.startsWith(DEV_PREFIX) && id.length > DEV_PREFIX.length;
const clip = (s) => (s.length > 12 ? s.slice(0, 11) + '…' : s);

// the short name drawn in the arena (Q18): the roster's tag for a house trenchie, the id (without `dev-`) for anyone else
export function shortName(roster, id) {
  const row = (roster || []).find((r) => r.trenchieId === id);
  if (row) return row.tag || row.name;
  return clip(isDev(id) ? id.slice(DEV_PREFIX.length) : id);
}
// the text the panel art draws (its tags are plain strings): a DEV identity carries the word
export const tagText = (roster, id) => (isDev(id) ? shortName(roster, id) + ' DEV' : shortName(roster, id));
