// The snapshot codec, JS half (W14). Today the arena server sends `server.encode_snapshot`: canonical JSON
//   [version, tick, names, rows, fighters, drops, objects, casts, events]
// as one text frame per tick. decode() turns it into plain objects the view reads; encode() writes it back byte for byte,
// which is the round-trip test (arena-codec-case.mjs). When near/arena/codec.py lands its own layout, only this file changes.

export const SNAPSHOT_VERSION = 1;
// the sorted slot order inside a fighter record (server.encode_snapshot sorts f["equipped"])
export const SLOTS = ['body', 'head', 'trinket', 'weapon'];
// sorted(rules["signatures"]) in the current rules table; a cast carries an index into it
export const SIGNATURES = ['beam_sweep', 'blink_strike', 'bubble', 'chain_storm', 'dodge_roll', 'magnet', 'shockwave'];
export const STATUS = ['alive', 'bench', 'left'];

export function decode(text) {
  const raw = typeof text === 'string' ? JSON.parse(text) : text;
  const [version, tick, names, rows, fighters, drops, objects, casts, events] = raw;
  if (version !== SNAPSHOT_VERSION) throw new Error('snapshot version ' + version + ' is not ' + SNAPSHOT_VERSION);
  return {
    version, tick, names, rows,
    fighters: fighters.map((f) => ({
      idx: f[0], id: names[f[0]], x: f[1], y: f[2], hp: f[3], dir: f[4], status: f[5],
      target: f[6] >= 0 ? names[f[6]] : null, sigCooldown: f[7],
      items: Object.fromEntries(f[8].map((r, i) => [SLOTS[i], rows[r]])), itemRows: f[8], shield: f[9],
    })),
    drops: drops.map((d) => ({ key: d[0], item: rows[d[1]], row: d[1], x: d[2], y: d[3], expires: d[4] })),
    objects: objects.map((o) => ({
      key: o[0], kind: o[1], x: o[2], y: o[3], resolveAt: o[4], tx: o[5], ty: o[6], vx: o[7], vy: o[8],
      range: o[9], angle: o[10], until: o[11], radius: o[12], width: o[13],
    })),
    casts: casts.map((c) => ({ who: names[c[0]], whoIdx: c[0], sig: SIGNATURES[c[1]], sigIdx: c[1], resolveAt: c[2], x: c[3], y: c[4] })),
    events,
  };
}

// The inverse of decode(). Key order is the server's (canonical JSON sorts object keys, no spaces).
export function encode(s) {
  const canon = (v) => {
    if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
    if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}';
    return JSON.stringify(v);
  };
  return canon([
    s.version, s.tick, s.names, s.rows,
    s.fighters.map((f) => [f.idx, f.x, f.y, f.hp, f.dir, f.status, f.target === null ? -1 : s.names.indexOf(f.target), f.sigCooldown, f.itemRows, f.shield]),
    s.drops.map((d) => [d.key, d.row, d.x, d.y, d.expires]),
    s.objects.map((o) => [o.key, o.kind, o.x, o.y, o.resolveAt, o.tx, o.ty, o.vx, o.vy, o.range, o.angle, o.until, o.radius, o.width]),
    s.casts.map((c) => [c.whoIdx, c.sigIdx, c.resolveAt, c.x, c.y]),
    s.events,
  ]);
}
