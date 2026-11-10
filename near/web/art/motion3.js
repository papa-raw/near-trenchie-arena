/* motion3.js — key poses and timing for the trenchies on the RIG3 joints (ES module).
 * Pure function of (state, weapon, age in ms): the same inputs always give the same pose, no clock and no random.
 *   import { applyMotion, STATES, WEAPONS, duration, install } from './motion3.js'
 *   applyMotion(trenchie, { state: 'attack', weapon: 'swing', age: 120, facing: 4 })
 * install() registers it as LOOK3's setPose, so trenchie.setPose({ state, weapon, age, facing }) works too.
 * The renderer owns position, facing and hitstop (a held body just stops advancing `age`); this file only moves joints.
 * States follow the sim: idle move windup attack telegraph signature dodge dash grab hitstun ko respawn swim_home.
 * Weapons: swing shot beam lob zap lunge. Poses are deltas from rest; angles in radians, offsets in tiles.
 */
import { LOOK3 } from './look3.js';

export const STATES = ['idle', 'move', 'windup', 'attack', 'telegraph', 'signature', 'dodge', 'dash', 'grab', 'hitstun', 'ko', 'respawn', 'swim_home'];
export const WEAPONS = ['swing', 'shot', 'beam', 'lob', 'zap', 'lunge'];

// pose fields: sx sy (base squash x/z and y), hop (base y), lean roll yaw (pivot rotation x z y), hx hy hz (weapon hand), lx ly lz (off hand),
// wx wy wz (weapon rotation), hdx hdz (head nod, tilt), fl fr (foot lift), sh (contact shadow scale)
const DEF = { sx: 1, sy: 1, sh: 1 };
const FIELDS = ['sx', 'sy', 'sh', 'hop', 'lean', 'roll', 'yaw', 'hx', 'hy', 'hz', 'lx', 'ly', 'lz', 'wx', 'wy', 'wz', 'hdx', 'hdz', 'fl', 'fr'];
const TAU = Math.PI * 2;

const ease = {
  io: (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2),
  out: (k) => 1 - Math.pow(1 - k, 3),
  in: (k) => k * k * k,
  back: (k) => { const s = 1.6, j = k - 1; return 1 + (s + 1) * j * j * j + s * j * j; }
};

// keyframes: [ms, pose, ease-into-this-key]; the last key holds. loop: the cycle length in ms, else the state's duration is its last key.
const KEYS = {
  windup: [[0, {}], [200, { lean: -0.18, sx: 1.05, sy: 0.93, hy: 0.08, wx: -0.4, wz: -0.3 }, 'out']],
  telegraph: [[0, {}], [260, { sx: 1.07, sy: 0.9, lean: -0.1, hy: 0.12, wx: -0.3 }, 'out']],
  signature: [[0, { sx: 1.07, sy: 0.9 }], [100, { hop: 0.2, sx: 0.92, sy: 1.12, hy: 0.2, hx: 0.05, wx: 0.3, wz: 0.9, lean: 0.05 }, 'out'], [260, { hop: 0.08, sx: 1.04, sy: 0.96, wx: 0.3, wz: 0.9 }], [420, {}]],
  dodge: [[0, {}], [50, { sy: 0.85, sx: 1.08 }, 'out'], [160, { lean: Math.PI, hop: 0.14, sx: 0.96, sy: 0.96, wx: 0.6, wz: 0.9 }, 'io'],
    [290, { lean: TAU, hop: 0.02, sx: 0.96, sy: 0.96, wx: 0.6, wz: 0.9 }, 'io'], [340, { lean: TAU, sy: 0.88, sx: 1.08 }, 'out'], [400, { lean: TAU }]],
  dash: [[0, {}], [90, { lean: 0.4, sx: 0.94, sy: 1.08, hz: 0.14, wx: 1.3, wz: 0.12, fl: 0.04, fr: 0.0 }, 'out'], [200, { lean: 0.4, sx: 0.94, sy: 1.08, hz: 0.14, wx: 1.3, wz: 0.12 }]],
  hitstun: [[0, {}], [40, { lean: -0.32, roll: 0.18, sx: 1.1, sy: 0.88, hop: 0.04, wx: -0.5, wz: 0.6, hdx: -0.15 }, 'out'],
    [200, { lean: -0.2, roll: 0.1, sx: 1.04, sy: 0.97, wx: -0.3, wz: 0.4 }], [350, {}]],
  ko: [[0, {}], [80, { sx: 1.12, sy: 0.85 }, 'out'], [300, { hop: 0.6, lean: -0.4, roll: 1.15, sx: 0.96, sy: 1.04, wx: -1, wz: -1.2, sh: 0.4 }, 'out'],
    [650, { hop: -0.04, lean: -0.3, roll: 1.4, sx: 1.06, sy: 0.9, wx: -1, wz: -1.2 }, 'in'], [760, { hop: 0.03, lean: -0.3, roll: 1.4, sx: 1.04, sy: 0.92, wx: -1, wz: -1.2 }, 'out'],
    [900, { hop: -0.04, lean: -0.3, roll: 1.45, sx: 1.1, sy: 0.86, wx: -1, wz: -1.2 }, 'in']],
  respawn: [[0, { sx: 0.05, sy: 0.05, sh: 0.1 }], [200, { sx: 1.15, sy: 1.2, hop: 0.1 }, 'out'], [330, { sx: 0.95, sy: 0.95 }], [450, {}]],
  grab: [[0, {}], [200, { lean: 0.35, sy: 0.9, sx: 1.05, hy: -0.12, hz: 0.08, hdx: 0.2 }], [400, { lean: 0.3, sy: 0.92, sx: 1.04, hy: -0.1, hz: 0.1, hdx: 0.18 }], [600, {}]]
};
KEYS.grab.loop = 600;
const ATTACK = {
  swing: [[0, {}], [90, { lean: -0.2, sx: 0.96, sy: 1.05, hy: 0.1, hz: -0.05, wx: -0.5, wz: -0.6, hdx: -0.1 }, 'io'],
    [150, { lean: 0.14, yaw: 0.5, roll: -0.1, sx: 1.06, sy: 0.94, hy: 0.1, hz: 0.08, wx: 1.25, wz: 1.15, hdx: 0.05 }, 'out'], [300, {}, 'io']],
  shot: [[0, {}], [80, { sx: 0.96, sy: 1.05, lean: -0.2, hx: -0.04, hy: 0.12, hz: -0.1, wx: -0.3, wz: -0.5, hdx: -0.08 }, 'io'],
    [120, { lean: 0.16, roll: -0.06, sx: 1.05, sy: 0.95, hz: 0.2, hy: 0.08, wx: 1.5, wz: 0.05, hdx: 0.06 }, 'out'],
    [170, { lean: -0.16, sx: 1.04, sy: 0.96, hz: 0.1, hy: 0.12, wx: 1.1, wz: 0.2 }, 'out'], [320, {}, 'io']],
  beam: [[0, {}], [300, { lean: 0.05, sx: 1.03, sy: 0.97, hz: 0.12, hy: 0.06, wx: 1.5, wz: 0.05 }, 'io'], [520, { lean: 0.05, sx: 1.03, sy: 0.97, hz: 0.12, hy: 0.06, wx: 1.5, wz: 0.05 }], [700, {}, 'io']],
  lob: [[0, {}], [120, { lean: -0.25, sy: 1.06, hy: 0.2, hz: -0.1, wx: -0.8, wz: 0.2 }, 'io'],
    [190, { lean: 0.2, hz: 0.14, hy: 0.12, wx: 1.1, wz: 0.1, sy: 0.95, sx: 1.05 }, 'out'], [420, {}, 'io']],
  zap: [[0, {}], [80, { lean: -0.1, hz: 0.1, wx: 0.9, wz: 0.3, sx: 0.98, sy: 1.03 }, 'io'],
    [140, { lean: 0.08, hz: 0.2, hy: 0.08, wx: 1.55, sx: 1.05, sy: 0.95, hdz: 0.1 }, 'out'], [360, {}, 'io']],
  lunge: [[0, {}], [100, { lean: -0.15, sx: 1.06, sy: 0.92, hz: -0.06, wx: 0.4, wz: 0.2 }, 'io'],
    [170, { lean: 0.38, sx: 0.94, sy: 1.08, hz: 0.16, hx: 0.06, wx: 1.42, wz: 0.12, hop: 0.03 }, 'out'], [360, {}, 'io']]
};

/** Length in ms of a state's one-shot motion, or the cycle length of a looping one. */
export function duration(state, weapon) {
  if (state === 'idle') return 1700; if (state === 'move') return 450; if (state === 'swim_home') return 700;
  const k = state === 'attack' ? ATTACK[weapon] || ATTACK.swing : KEYS[state] || [[0, {}]];
  return k.loop || k[k.length - 1][0];
}
export function isLoop(state) { return state === 'idle' || state === 'move' || state === 'swim_home' || state === 'grab'; }

function sample(keys, t) {
  if (t <= keys[0][0]) return Object.assign({}, keys[0][1]);
  const last = keys[keys.length - 1];
  if (t >= last[0]) return Object.assign({}, last[1]);
  let i = 0; while (keys[i + 1][0] <= t) i++;
  const a = keys[i], b = keys[i + 1], k = (ease[b[2]] || ease.io)((t - a[0]) / (b[0] - a[0])), out = {};
  for (const f of FIELDS) {
    const d = DEF[f] === undefined ? 0 : DEF[f], va = a[1][f] === undefined ? d : a[1][f], vb = b[1][f] === undefined ? d : b[1][f];
    if (va !== d || vb !== d) out[f] = va + (vb - va) * k;
  }
  return out;
}

/** The pose (field deltas) for a state at an age, and the face to show. */
export function poseAt(state, weapon, age) {
  age = Math.max(0, age || 0);
  switch (state) {
    case 'idle': { const b = Math.sin(age / 1700 * TAU); return { pose: { sx: 1 + 0.015 * b, sy: 1 - 0.02 * b, hy: 0.01 * b }, face: age % 3200 < 110 ? 'blink' : 'normal' }; }
    case 'move': {
      const p = age / 450 * TAU;
      return { pose: { hop: Math.abs(Math.sin(p)) * 0.035, roll: Math.sin(p) * 0.07, lean: 0.12, sx: 1 + 0.02 * Math.cos(2 * p), sy: 1 - 0.02 * Math.cos(2 * p),
        hz: Math.sin(p) * 0.05, fl: Math.max(0, Math.sin(p)) * 0.05, fr: Math.max(0, -Math.sin(p)) * 0.05 }, face: 'normal' };
    }
    case 'swim_home': {
      const p = age / 700 * TAU;
      return { pose: { hop: -0.06 + Math.sin(p) * 0.02, roll: Math.sin(p) * 0.1, lean: 0.1, hz: Math.sin(p) * 0.06, hy: 0.05, lz: Math.sin(p + Math.PI) * 0.05, sh: 0.0 }, face: 'normal' };
    }
    case 'attack': return { pose: sample(ATTACK[weapon] || ATTACK.swing, age), face: 'normal' };
    case 'telegraph': { const P = sample(KEYS.telegraph, age); P.roll = Math.sin(age * 0.06) * 0.03; return { pose: P, face: 'normal' }; }
    case 'grab': return { pose: sample(KEYS.grab, age % 600), face: 'normal' };
    case 'hitstun': return { pose: sample(KEYS.hitstun, age), face: age < 250 ? 'hurt' : 'normal' };
    case 'ko': { const P = sample(KEYS.ko, age); if (P.hop !== undefined && P.hop > 0.02) P.sh = Math.max(0.35, 1 - P.hop * 0.9); return { pose: P, face: age > 60 ? 'ko' : 'hurt' }; }
    default: return { pose: sample(KEYS[state] || [[0, {}]], age), face: 'normal' };
  }
}

const RESTS = new WeakMap();
function rest(t) {
  let r = RESTS.get(t); if (r) return r;
  const J = t.joints;
  r = { hR: J.handR.position.clone(), hL: J.handL.position.clone(), fL: J.footL.position.clone(), fR: J.footR.position.clone(), sh: J.shadow.scale.clone(), baseY: J.base.scale.y, shadowVisible: true };
  RESTS.set(t, r); return r;
}

/** Move a trenchie's joints to the pose for (state, weapon, age). Never touches root position; sets root.rotation.y when facing is given. */
export function applyMotion(t, p) {
  p = p || {};
  const J = t.joints, r = rest(t), s = poseAt(p.state || 'idle', p.weapon, p.age || 0), P = s.pose, g = (f) => (P[f] === undefined ? (DEF[f] === undefined ? 0 : DEF[f]) : P[f]);
  J.base.scale.set(g('sx'), g('sy') * (p.bodyScaleY || 1), g('sx')); J.base.position.y = g('hop');
  J.pivot.rotation.set(g('lean'), g('yaw'), g('roll'));
  J.handR.position.set(r.hR.x + g('hx'), r.hR.y + g('hy'), r.hR.z + g('hz'));
  J.handL.position.set(r.hL.x + g('lx'), r.hL.y + g('ly'), r.hL.z + g('lz'));
  J.mountWeapon.rotation.set(g('wx'), g('wy'), g('wz'));
  J.head.rotation.set(g('hdx'), 0, g('hdz'));
  J.footL.position.set(r.fL.x, r.fL.y + g('fl'), r.fL.z); J.footR.position.set(r.fR.x, r.fR.y + g('fr'), r.fR.z);
  const sh = g('sh'); J.shadow.scale.set(r.sh.x * Math.max(sh, 0.001), r.sh.y * Math.max(sh, 0.001), 1); J.shadow.visible = sh > 0.02;
  t.setFace(s.face);
  if (p.facing !== undefined) J.root.rotation.y = LOOK3.facingRotY(p.facing);
  return s;
}

/** Register as LOOK3's setPose (t.setPose({ state, weapon, age, facing })). */
export function install() { LOOK3.setMotion({ apply: applyMotion }); }
