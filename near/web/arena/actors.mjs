// The trenchies: one three.js Group per fighter (W8), built by the approved B3 bodies (LOOK3.makeTrenchie), worn items riding
// the body's joints, and the motion that sells a fight, from the feel spec: anticipation drawn from the buffer's look-ahead,
// a walk locked to distance, per-body hitstop with vibration, hit shove and squash, the KO beat, bench and arrival.
// Everything here is render-only and a pure function of (events seen, render time): scrubbing or replaying reproduces it.
import * as THREE from 'three';
import { arenaTessellation } from './tessellation.mjs';
import { milliToWorld, angleToRotY, angleDelta, lerpAngle } from './frame.mjs';
import { TICK_MS } from './buffer.mjs';
import { FADE_MS } from './prejump.mjs';
import { weaponRenderScale as scaleFor } from './weapon-scale.mjs';
export { WEAPON_SCALE } from './weapon-scale.mjs';

export const BODY_SCALE = 2;                // the look3 body is 0.66 tall; the sim keeps bodies 1.3 tiles apart
// Board 3 (how fights move, A Heavy toon): every held weapon is drawn 2.5x on its mount (a /2 weapon at 1x), so a swing stick
// reaches about the swing's own hit range. Render scale only: no item, kit or validator change (WEAPON-LIMITS.md).
export const weaponRenderScale = (itemRenderer, id) => scaleFor(id, itemRenderer?.specs, itemRenderer?.records);
const k01 = (t, a, b) => Math.min(1, Math.max(0, (t - a) / (b - a)));
const eOut = (k) => 1 - Math.pow(1 - Math.min(1, Math.max(0, k)), 3);
const eIn = (k) => Math.pow(Math.min(1, Math.max(0, k)), 3);
const clamp01 = (k) => Math.min(1, Math.max(0, k));
// closed-form damped spring from 0 to 1 (feel spec: playful k200 d12, default k170 d26)
function spring(t, k, d) {
  if (t <= 0) return 0;
  const w = Math.sqrt(k), z = d / (2 * w), wd = w * Math.sqrt(Math.max(1e-6, 1 - z * z));
  return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t));
}

// FEEL: one table (W11). Durations in ms. Distances named ...Local are in the body's local units, and 1 local unit is 2 tiles
// at BODY_SCALE 2 (the body is drawn 2x; corrected 2026-11-12, the comment said 0.5 tile). The walk's bobLocal 0.03 (0.06 tile),
// footSweepLocal 0.07 (0.14), footLiftLocal 0.04 (0.08) and the lunge's 0.14 pivot step (0.28) were tuned by eye in local units
// and are kept. Distances named ...Tiles are world tiles, applied to the body's position or divided by BODY_SCALE on a joint.
export const FEEL = {
  anticipationMs: 150, anticipationShortMs: 100, strikeMs: 50, followMs: 220,
  hitstopLightMs: 50, hitstopHeavyMs: 100, hitstopKoMs: 200, crowdN: 4, crowdR: 3.0, crowdScale: 0.75, heavyHit: 18,
  squashMs: 160, shoveMs: 200, flashCap: 0.6,
  koLaunchMs: 650,
  // board 3, A Heavy toon (final/SPEC.md); distances in tiles
  anticipationShotMs: 120, hitVibTiles: 0.05, koVibTiles: 0.07, flashHit: 0.6, flashKo: 1.0, flashIntensity: 0.7,
  shoveLightTiles: 0.22, shoveHeavyTiles: 0.45, shoveBackFromMs: 420, shoveBackToMs: 900,
  koTiles: 3.2, koPeakTiles: 2.2, koSpin: 3 * Math.PI, koBounceMs: 250, koBounceTiles: 0.5, koRoll: 1.3, koHideMs: 1500,
  waveTiles: 0.8, waveHopTiles: 0.5, waveMs: 700, waveHopMs: 450,
  shoulderOutMs: 120, shoulderLeaveMs: 60, shoulderLeaveOverMs: 50,
  attackMs: { swing: 300, lunge: 360, shot: 320, lob: 380, beam: 700, zap: 320 },   // motion3's, in this file's attack age (the lob's starts 40 ms in)
  stepLenTiles: 1.0, bobLocal: 0.03, footSweepLocal: 0.07, footLiftLocal: 0.04,
  walkMinSpeed: 0.001, walkMinStride: 0.35, // ignore sub-milli-tile/s noise; slow approaches still have visible steps
  turnDegreesPerSecond: 720,       // a half-turn takes 250 ms; body heading cannot twitch across the ring in one frame
};

// The swing is an overhead slam (final/SPEC.md section 2a): the stick rises up and back, comes down in the vertical plane
// from the hand to the target, and the hand slides up the shaft (a choke) so the head lands on the target's crown, at the
// sim's 1.3-tile range, on the hit tick; the rest of the shaft rises behind the hand, over everyone's heads.
export const SLAM = { raise: 0.55, out: 0.12, hop: 0.13, back: 2.25, chokeBelow: 0.45, lean: 0.06, crownY: 1.36, crownIn: 0.12 };   // raise/out/hop in body units (x2 = tiles), angles in rad
export const crownOf = (src, dst) => { const dx = dst.x - src.x, dz = dst.z - src.z, L = Math.hypot(dx, dz) || 1; return { x: dst.x - dx / L * SLAM.crownIn, y: SLAM.crownY, z: dst.z - dz / L * SLAM.crownIn }; };

const PALETTE = ['p07', 'p09', 'p11', 'p14', 'p12', 'p08', 'p10', 'p15'];
function hashString(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

// A KITS.roster row for a fighter id; ids the roster does not know (anyone who snaps in) get a body colour from their id.
export function rosterRow(KITS, id, items) {
  const hit = [...(KITS.roster || []), ...(KITS.players || [])].find((r) => r.trenchieId === id);
  if (hit) return hit;
  const h = hashString(id);
  return { trenchieId: id, name: id, tag: id.length > 12 ? id.slice(0, 11) + '…' : id, paletteIds: [PALETTE[h % PALETTE.length], 'p04'], kit: items || {} };
}

// the held weapon's extent along its own shaft (item local +y), in world tiles from the grip: how far the slam's head reaches
function shaftTip(a) {
  const M = a.J.mountWeapon, item = M.children[0]; if (!item) return 0;
  a.h.object3d.updateMatrixWorld(true);
  const o = M.getWorldPosition(new THREE.Vector3()), ax = new THREE.Vector3(0, 1, 0).applyQuaternion(item.getWorldQuaternion(new THREE.Quaternion())), v = new THREE.Vector3();
  let hi = 0;
  item.traverse((m) => { if (m.isMesh) { const pa = m.geometry.attributes.position; for (let i = 0; i < pa.count; i++) hi = Math.max(hi, v.fromBufferAttribute(pa, i).applyMatrix4(m.matrixWorld).sub(o).dot(ax)); } });
  return hi;
}

class Actor {
  constructor(id, handle, row, scene) {
    this.id = id; this.h = handle; this.row = row; this.scene = scene;
    const J = handle.joints; this.J = J;
    this.baseScaleY = J.base.scale.y;
    this.def = { hand: J.handR.position.clone(), handL: J.handL.position.clone(), footL: J.footL.position.clone(), footR: J.footR.position.clone(), pivot: J.pivot.position.clone() };
    this.phi = 0; this.px = null; this.pz = null; this.speed = 0;
    this.walkPose = [0, 0, 0, 0, 0]; // bob, sweep, left/right lift, lean; retained through hitstop
    this.heading = null; this.poseTick = null; this.poseState = null;
    this.anims = [];                 // {kind, tick, ...} fired from events; evaluated against the render tick
    this.hpMax = 100; this.lastAlive = null;
    this.koAt = null; this.koTick = null; this.arriveAt = null;
    this.blinkAt = 2500 + (hashString(id) % 3000); this.blinkEnd = 0;
    this.face = 'normal'; this.items = null; this.worn = []; this.shieldMesh = null;
    this.hitDir = { x: 0, z: 0 };
    this.holds = [];                 // {from, until, vib} in render ms: per-body hitstop (board 3)
    this.koDir = { x: 0, z: 1 };     // the sim's KO direction: from the KO-er to this body, at the KO tick
    this.flashNow = 0; this.shoulderRest = J.mountWeapon.quaternion.clone(); this.mountPosRest = J.mountWeapon.position.clone();
    this.shaftTip = 0; this.slam = null;   // the held weapon's reach along its shaft (tiles, from the grip); the slam's state this frame
    // Each body flashes alone: its own material copies (look3's flash() shares a timer across the scene).
    this.bodyMeshes = [];
    handle.object3d.traverse((o) => { if (o.isMesh && o.material && !Array.isArray(o.material)) { o.material = o.material.clone(); if (o.material.emissive) this.bodyMeshes.push(o); } });
  }
}
const PQ = new THREE.Quaternion(), RQ = new THREE.Quaternion(), IQ = new THREE.Quaternion();
const TILT = new THREE.Quaternion().setFromEuler(new THREE.Euler(-0.22, 0, -0.18));
const UP = new THREE.Vector3(0, 1, 0), BX = new THREE.Matrix4(), QS = new THREE.Quaternion(), NO_TURN = new THREE.Quaternion();
const MELEE = new Set(['swing', 'lunge']);

export class Actors {
  constructor(scene, LOOK3, KITS, itemRenderer, { arenaQuality = false } = {}) {
    this.scene = scene; this.LOOK3 = LOOK3; this.KITS = KITS; this.itemRenderer = itemRenderer; this.map = new Map();
    this.arenaQuality = arenaQuality; itemRenderer.arenaQuality = arenaQuality;
    this.crowd = new Map();         // id -> number of live bodies within crowdR (hitstop scale)
    this.early = new Map();         // id -> hits and KOs that fired before its body was built (the page's first frame)
  }

  get(id) { return this.map.get(id); }

  // the world point of a fighter's weapon mount (where a shot or lob leaves), and the world scale of a held weapon's
  // grip at mount scale 1 (a dropped weapon lies at the size it was held)
  tip(id) { const a = this.map.get(id); if (!a) return null; a.J.mountWeapon.updateWorldMatrix(true, false); return a.J.mountWeapon.getWorldPosition(new THREE.Vector3()); }
  mountWorldScale() {
    for (const a of this.map.values()) { a.J.mountWeapon.updateWorldMatrix(true, false); const v = a.J.mountWeapon.getWorldScale(new THREE.Vector3()); return v.x / a.J.mountWeapon.scale.x; }
    return null;
  }

  ensure(f) {
    let a = this.map.get(f.id);
    if (a) return a;
    const row = rosterRow(this.KITS, f.id, f.items);
    const player = (this.KITS.players || []).find((r) => r.trenchieId === f.id);
    const handle = player && globalThis.S3 ? globalThis.S3.make({ body: player.paletteIds?.[0] || 'p07', hairCol: player.paletteIds?.[1] || 'p03', ...player.look, hat: 'hide' }, { items: false }) : this.LOOK3.makeTrenchie({ ...row, kit: {} });
    handle.object3d.scale.setScalar(BODY_SCALE);
    handle.object3d.traverse((o) => { if (o.isMesh) o.castShadow = o.name !== 'shadow'; });
    if (this.arenaQuality) arenaTessellation(handle.object3d);
    this.scene.add(handle.object3d);
    a = new Actor(f.id, handle, row, this.scene);
    this.map.set(f.id, a);
    for (const replay of this.early.get(f.id) || []) replay();   // its body exists now: the events it missed apply from their own ticks
    this.early.delete(f.id);
    return a;
  }

  setItems(a, f) {
    const key = JSON.stringify(f.items);
    if (a.items === key) return;
    a.items = key;
    this.itemRenderer.clear(a.h);
    a.worn = this.itemRenderer.equip(a.h, f.items);
    a.J.mountWeapon.scale.setScalar(weaponRenderScale(this.itemRenderer, f.items && f.items.weapon));
    a.shaftTip = shaftTip(a);
    a.casts = null; a.flashNow = -1;   // new item materials: write the flash state again
  }

  // ---- events fired from the buffer ------------------------------------------------------------------------------------
  // called early (look-ahead) so the wind-up can be drawn before the strike; o: {dx, dz, src, dst} (world, at the attack tick;
  // dst is the target a swing slams: its first hit, else the fighter's target)
  onAttack(ev, tick, o = {}) {
    const a = this.map.get(ev.fighter); if (!a) return;
    a.anims.push({ kind: 'attack', tick, weapon: ev.weapon, dirx: o.dx || 0, dirz: o.dz || 0, target: o.target || null, crown: ev.weapon === 'swing' && o.src && o.dst ? crownOf(o.src, o.dst) : null });
  }
  // Board 3: every hit and KO is timed from its own sim tick (render time = tick x 50 ms), never from the wall clock, so a
  // replay, a scrub or slow-mo draws the same frame; nothing here sends an input or moves a tick.
  hitstopMs(id, heavy) { return (heavy ? FEEL.hitstopHeavyMs : FEEL.hitstopLightMs) * ((this.crowd.get(id) || 0) >= FEEL.crowdN ? FEEL.crowdScale : 1); }
  later(id, fn) { const q = this.early.get(id) || []; q.push(fn); if (q.length > 16) q.shift(); this.early.set(id, q); }   // bounded: a body that never comes
  onHit(ev, tick, nowMs, srcPos, dstPos) {
    const a = this.map.get(ev.target); if (!a) return this.later(ev.target, () => Actors.prototype.onHit.call(this, ev, tick, nowMs, srcPos, dstPos));
    const heavy = ev.damage >= FEEL.heavyHit, ms = this.hitstopMs(ev.target, heavy), at = tick * TICK_MS;
    a.holds.push({ from: at, until: at + ms, vib: FEEL.hitVibTiles, flash: FEEL.flashHit });
    let dx = 0, dz = 0;
    if (srcPos && dstPos) { dx = dstPos.x - srcPos.x; dz = dstPos.z - srcPos.z; const L = Math.hypot(dx, dz) || 1; dx /= L; dz /= L; }
    a.anims.push({ kind: 'hit', tick, dmg: ev.damage, dx, dz, heavy, hold: ms, wave: ev.move === 'shockwave' });
    if (heavy) a.anims.push({ kind: 'hurtface', tick });
    // in melee the attacker holds too, for the whole hold
    const s = this.map.get(ev.source); if (s && s !== a && MELEE.has(ev.move)) s.holds.push({ from: at, until: at + ms, vib: 0, flash: 0 });
  }
  onKo(ev, tick, nowMs, srcPos, dstPos) {
    const a = this.map.get(ev.fighter); if (!a) return this.later(ev.fighter, () => Actors.prototype.onKo.call(this, ev, tick, nowMs, srcPos, dstPos));
    const at = tick * TICK_MS;
    a.koAt = at; a.koTick = tick;
    a.holds.push({ from: at, until: at + FEEL.hitstopKoMs, vib: FEEL.koVibTiles, flash: FEEL.flashKo, ko: true });
    if (srcPos && dstPos && (srcPos.x !== dstPos.x || srcPos.z !== dstPos.z)) { const dx = dstPos.x - srcPos.x, dz = dstPos.z - srcPos.z, L = Math.hypot(dx, dz); a.koDir = { x: dx / L, z: dz / L }; }
    else { const r = a.h.object3d.rotation.y; a.koDir = { x: -Math.sin(r), z: -Math.cos(r) }; }   // no KO-er: knocked backwards
    const s = ev.source && this.map.get(ev.source); if (s && s !== a) s.holds.push({ from: at, until: at + FEEL.hitstopKoMs, vib: 0, flash: 0 });
  }
  // Keep the old standing pose through a plain fade, then use the new life's ring position.
  onRespawn(ev, tick, nowMs) {
    const a = this.map.get(ev.fighter); if (!a) return;
    if (a.departure) this.fade(a, 1);
    a.arriveAt = nowMs; a.koAt = null;
    a.departure = { position: a.h.object3d.position.clone(), rotation: a.h.object3d.rotation.clone(), scale: a.h.object3d.scale.clone(),
      basePosition: a.J.base.position.clone(), baseScale: a.J.base.scale.clone(), materials: new Map() };
    a.departure.baseScale.y /= a.baseScaleY;
  }

  // Actor/body and worn-item materials are owned per fighter. Restore their original alpha/depth state after fading.
  fade(a, amount) {
    const saved = a.departure.materials;
    a.h.object3d.traverse((node) => {
      for (const material of [].concat(node.material || [])) {
        if (!saved.has(material)) saved.set(material, { opacity: material.opacity, transparent: material.transparent, depthWrite: material.depthWrite });
        const before = saved.get(material), transparent = amount < 1 || before.transparent;
        material.opacity = before.opacity * amount; material.depthWrite = amount < 1 ? false : before.depthWrite;
        if (material.transparent !== transparent) { material.transparent = transparent; material.needsUpdate = true; }
      }
    });
  }

  // ---- one frame -------------------------------------------------------------------------------------------------------
  // fighters: [{id, x, y (milli), dir (deg), status, hp, shield, items, itemRows}] interpolated for this frame
  update(fighters, renderTick, nowMs, dtMs, bench, casting = new Set()) {
    const rtMs = renderTick * TICK_MS;
    const live = fighters.filter((f) => f.status === 0);
    // crowd density for hitstop scale
    for (const f of live) { let n = 0; for (const g of live) if (Math.hypot(f.x - g.x, f.y - g.y) / 1000 <= FEEL.crowdR) n++; this.crowd.set(f.id, n); }

    const out = new Map();
    for (const f of fighters) {
      const a = this.ensure(f);
      this.setItems(a, f);
      a.hpMax = Math.max(a.hpMax, f.hp);
      const o = a.h.object3d;
      let x = f.x, y = f.y, dir = f.dir, state = 'alive';
      if (f.status === 0) a.lastAlive = { x, y, dir };
      else {
        const sinceKo = a.koAt === null ? Infinity : rtMs - a.koAt;
        // the KO path runs at the spot it fell: freeze, launch, bounce, lie, poof; then the shore bench as before
        if (a.lastAlive && sinceKo < FEEL.hitstopKoMs + FEEL.koHideMs) { x = a.lastAlive.x; y = a.lastAlive.y; dir = a.lastAlive.dir; state = 'ko'; }
        else { const seat = bench.get(f.id); if (seat) { x = seat.x; y = seat.y; dir = seat.dir; } state = 'bench'; }
      }
      const w = milliToWorld(x, y);
      o.position.set(w.x, 0, w.z);
      o.visible = f.status !== 2;
      out.set(f.id, { x: w.x, z: w.z, state, f });
      this.pose(a, f, state, w, dir, renderTick, nowMs, dtMs, casting.has(f.id));
      a.J.base.scale.y *= a.baseScaleY;
      out.get(f.id).lift = a.J.base.position.y * BODY_SCALE; // a body dropping in or knocked up: its tag follows it
    }
    // drop actors whose fighter left the snapshot
    for (const [id, a] of this.map) if (!out.has(id)) { this.scene.remove(a.h.object3d); a.h.dispose(); this.map.delete(id); }
    return out;
  }

  pose(a, f, state, w, dir, rt, now, dt, casting = false) {
    const J = a.J, o = a.h.object3d, rtMs = rt * TICK_MS;
    o.rotation.set(0, 0, 0);
    // reset the joints this module drives
    J.base.scale.set(1, 1, 1); J.base.position.set(0, 0, 0); J.pivot.position.copy(a.def.pivot); J.pivot.rotation.set(0, 0, 0);
    J.handR.position.copy(a.def.hand); J.handL.position.copy(a.def.handL); J.footL.position.copy(a.def.footL); J.footR.position.copy(a.def.footR);
    o.scale.setScalar(BODY_SCALE);
    // bodies waiting on the shore cast no shadow: the ring holds 4 to 6, so most of the 14 are idle (budget lever)
    const casts = state !== 'bench';
    if (a.casts !== casts) { a.casts = casts; o.traverse((m) => { if (m.isMesh && m.name !== 'shadow') m.castShadow = casts; }); }

    // hitstop per body (FEEL): the pose holds while the world goes on; the held target trembles and flashes white
    let flash = 0, vib = 0, frozen = false;
    for (let i = a.holds.length - 1; i >= 0; i--) {
      const h = a.holds[i];
      if (rtMs >= h.until + 2000) { a.holds.splice(i, 1); continue; }
      if (rtMs >= h.from && rtMs < h.until) { frozen = frozen || state === 'alive' || h.ko; flash = Math.max(flash, h.flash); vib = Math.max(vib, h.vib); }
    }
    if (vib) { const s = Math.sin(rtMs * 1.7 + a.id.length); o.position.x += s * vib; o.position.z += Math.cos(rtMs * 1.3) * vib * 0.5; }
    this.setFlash(a, flash);
    const jump = a.px !== null && Math.hypot(w.x - a.px, w.z - a.pz) >= 1.5;
    if (a.heading === null || state !== 'alive' || a.poseState !== state || rt < a.poseTick || jump) a.heading = dir;
    else if (!frozen) {
      const turn = angleDelta(a.heading, dir), limit = FEEL.turnDegreesPerSecond * Math.max(0, rt - a.poseTick) * TICK_MS / 1000;
      a.heading += Math.max(-limit, Math.min(limit, turn));
    }
    a.poseTick = rt; a.poseState = state;
    o.rotation.y = angleToRotY(a.heading);
    // a hold freezes the walk and every attack's age (the slam's head stays on the crown); the shove waits out the hold
    const heldSince = (ms) => a.holds.reduce((n, h) => n + Math.max(0, Math.min(h.until, rtMs) - Math.max(h.from, ms)), 0);

    // walk, locked to distance: the step phase advances by tiles moved, never by time
    if (a.px !== null && state === 'alive' && !frozen) {
      const moved = Math.hypot(w.x - a.px, w.z - a.pz);
      if (moved < 1.5) a.phi += moved / FEEL.stepLenTiles;
      a.speed = dt > 0 ? (moved / dt) * 1000 : a.speed; // tiles per second
    }
    a.px = w.x; a.pz = w.z;
    const moving = state === 'alive' && !frozen && a.speed > FEEL.walkMinSpeed;
    const sw = Math.min(1, Math.max(FEEL.walkMinStride, a.speed / 3));
    const ph = a.phi * Math.PI;
    if (!frozen || state !== 'alive') {
      a.walkPose = moving ? [Math.abs(Math.sin(ph)) * FEEL.bobLocal * sw, Math.sin(ph) * FEEL.footSweepLocal * sw,
        Math.max(0, Math.cos(ph)) * FEEL.footLiftLocal * sw, Math.max(0, -Math.cos(ph)) * FEEL.footLiftLocal * sw, 0.08 * sw] : [0, 0, 0, 0, 0];
    }
    const [bob, sweep, leftLift, rightLift, walkLean] = a.walkPose;
    J.base.position.y += bob;
    J.footL.position.z += sweep; J.footR.position.z -= sweep;
    J.footL.position.y += leftLift; J.footR.position.y += rightLift;
    J.handL.position.z -= sweep * 0.8; J.pivot.rotation.x += walkLean;
    if (!moving && state === 'alive' && !frozen) {
      const b = Math.sin(now / 420 + a.row.trenchieId.length), k = 0.015;
      J.base.scale.set(1 + k * b, 1 - k * 1.3 * b, 1 + k * b);
    }

    let face = 'normal';
    if (now > a.blinkAt && a.blinkEnd === 0) a.blinkEnd = now + 70;
    if (a.blinkEnd && now < a.blinkEnd) face = 'blink'; else if (a.blinkEnd && now >= a.blinkEnd) { a.blinkEnd = 0; a.blinkAt = now + 3000 + (hashString(a.id + Math.floor(now / 1000)) % 2200); }

    // anims
    const dirx = Math.cos(dir * Math.PI / 180), dirz = Math.sin(dir * Math.PI / 180);
    const cosR = Math.cos(o.rotation.y), sinR = Math.sin(o.rotation.y);
    const toLocal = (x, z) => ({ x: x * cosR - z * sinR, z: x * sinR + z * cosR }); // world horizontal -> root-local
    let attackShoulder = 1;   // 1: shouldered; 0: held out at full length (inside an attack)
    let aim = null, upright = 0;   // the attack's facing, for where the stick goes out; how far a shove stands it up
    let slam = null;          // the swing this frame: {m, age}
    for (let i = a.anims.length - 1; i >= 0; i--) {
      const m = a.anims[i]; let u = (rt - m.tick) * TICK_MS; // ms relative to the event's tick
      if (m.kind === 'attack') {
        const lead = m.weapon === 'shot' ? FEEL.anticipationShotMs : m.weapon === 'zap' ? FEEL.anticipationShortMs : FEEL.anticipationMs;
        const dur = FEEL.attackMs[m.weapon] || FEEL.attackMs.swing;
        if (u > 0) u = Math.max(0, u - heldSince(m.tick * TICK_MS));   // hitstop holds the attacker at the strike
        if (u > Math.max(FEEL.strikeMs + FEEL.followMs, dur - lead)) { a.anims.splice(i, 1); continue; }
        if (u < -lead) continue;
        const age = u + lead;
        if (m.weapon === 'swing' && m.crown) { slam = { m, age }; continue; }   // the slam poses the whole body and the stick (below)
        // lunge, shot, lob (and zap) keep the stick shouldered through the windup: it leaves 60 ms before the strike over 50 ms,
        // and is back over the last 120 ms; the beam leaves at once (SPEC section 2)
        const leave = m.weapon === 'beam' ? 0 : lead - FEEL.shoulderLeaveMs;
        const sh = Math.max(1 - k01(age, leave, leave + FEEL.shoulderLeaveOverMs), k01(age, dur - FEEL.shoulderOutMs, dur));
        if (sh < attackShoulder) { attackShoulder = sh; aim = { x: m.dirx, z: m.dirz }; }
        let reach = 0, lean = 0, rise = 0;
        if (u > FEEL.strikeMs + FEEL.followMs) continue;
        if (u < 0) { const k = eIn((u + lead) / lead); reach = -0.10 * k; lean = -0.14 * k; rise = 0.03 * k; }       // pull back, away from the target
        else if (u < FEEL.strikeMs) { const k = eOut(u / FEEL.strikeMs); reach = -0.10 + 0.34 * k; lean = -0.14 + 0.34 * k; rise = 0.03 * (1 - k); } // strike
        else { const k = spring((u - FEEL.strikeMs) / 1000, 200, 12); reach = 0.24 * (1 - k); lean = 0.20 * (1 - spring((u - FEEL.strikeMs) / 1000, 170, 26)); }  // follow-through on the playful spring
        J.handR.position.z += reach; J.handR.position.y += rise; J.pivot.rotation.x += lean;
        if (m.weapon === 'lunge' && u >= 0 && u < 250) J.pivot.position.z += 0.14 * Math.sin(Math.PI * clamp01(u / 250));
      } else if (m.kind === 'hit') {
        // after the hold: slide away from the attacker (0.22 / 0.45 tiles, ease-out 200 ms) and back by 900 ms; a render
        // offset over the sim's position, which always wins
        const T = u - m.hold; if (u > FEEL.shoveBackToMs + m.hold) { a.anims.splice(i, 1); continue; }
        if (T < 0) continue;
        const push = m.wave ? 0 : m.heavy ? FEEL.shoveHeavyTiles : FEEL.shoveLightTiles;
        const k = eOut(k01(T, 0, FEEL.shoveMs)) * (1 - k01(u, FEEL.shoveBackFromMs, FEEL.shoveBackToMs));
        upright = Math.max(upright, k);   // a shoved body's stick stands straight up, so it does not lean into a neighbour
        o.position.x += m.dx * push * k; o.position.z += m.dz * push * k;
        if (m.wave) { // the shockwave: pushed out up to 0.8 tiles and back over 700 ms, with a 0.5-tile hop
          const kw = Math.sin(Math.PI * k01(T, 0, FEEL.waveMs)) * FEEL.waveTiles;
          o.position.x += m.dx * kw; o.position.z += m.dz * kw;
          J.base.position.y += Math.sin(Math.PI * k01(T, 0, FEEL.waveHopMs)) * FEEL.waveHopTiles / BODY_SCALE;
        }
        const L = toLocal(m.dx, m.dz), lean = (T < 60 ? eOut(T / 60) : 1 - eOut(k01(T, 60, FEEL.shoveMs))) * 0.16;
        J.pivot.rotation.x += -L.z * lean; J.pivot.rotation.z += L.x * lean;
        const sq = (T < 40 ? eOut(T / 40) : 1 - eOut(k01(T, 40, FEEL.squashMs))) * (m.heavy ? 0.14 : 0.1);
        J.base.scale.set(J.base.scale.x * (1 + sq * 0.9), J.base.scale.y * (1 - sq), J.base.scale.z * (1 + sq * 0.9));
      } else if (m.kind === 'hurtface') { if (u < 200) face = 'hurt'; else a.anims.splice(i, 1); }
    }

    // KO beat (feel row 10): freeze + flash, launch up and roll back, hold, then to the bench
    if (state === 'ko') {
      // board 3's KO (Pat, item 34): a 200 ms freeze with a white flash, then a 3.2-tile arc along the sim's KO direction
      // peaking 2.2 tiles high while spinning 3 pi, one 0.5-tile bounce, a lie on its side, and gone at +1500 ms (the poof)
      const T = rtMs - a.koAt - FEEL.hitstopKoMs;
      if (T < 0) face = 'hurt';
      else {
        const k = k01(T, 0, FEEL.koLaunchMs), d = FEEL.koTiles * eOut(k);
        o.position.x += a.koDir.x * d; o.position.z += a.koDir.z * d;
        o.position.y = Math.sin(Math.PI * k) * FEEL.koPeakTiles + (k >= 1 ? Math.abs(Math.sin(Math.PI * k01(T, FEEL.koLaunchMs, FEEL.koLaunchMs + FEEL.koBounceMs))) * FEEL.koBounceTiles : 0);
        const roll = FEEL.koRoll * eOut(k01(T, FEEL.koLaunchMs, FEEL.koLaunchMs + 100));
        o.rotation.x = roll * 0.25; o.rotation.z = roll; o.rotation.y += FEEL.koSpin * k;
        o.visible = o.visible && T < FEEL.koHideMs;
        face = 'ko';
      }
    } else if (state === 'bench') {
      o.scale.setScalar(BODY_SCALE * 0.9); // waiting on the shore: idle, facing the ring
    }
    if (face !== a.face) { a.h.setFace(face); a.face = face; }

    // spawn / signature shield: a pale bubble
    if (f.shield > 0 && state === 'alive') {
      if (!a.shieldMesh) { a.shieldMesh = new THREE.Mesh(new THREE.SphereGeometry(0.62, 20, 14), new THREE.MeshBasicMaterial({ color: '#D3F1E6', transparent: true, opacity: 0.28, depthWrite: false })); a.shieldMesh.position.y = 0.4; J.root.add(a.shieldMesh); }
      a.shieldMesh.visible = true; a.shieldMesh.scale.setScalar(1 + 0.04 * Math.sin(now / 120));
    } else if (a.shieldMesh) a.shieldMesh.visible = false;
    if (slam && state === 'alive') this.slamPose(a, slam.m.crown, slam.age, casting);
    else { a.slam = null; this.shoulder(a, state === 'ko' ? 1 : attackShoulder, casting, { aim, upright, ko: state === 'ko' }); }
    if (a.departure) {
      const t = now - a.arriveAt;
      if (state === 'alive' && t <= FADE_MS) {
        o.position.copy(a.departure.position); o.rotation.copy(a.departure.rotation); o.scale.copy(a.departure.scale);
        J.base.position.copy(a.departure.basePosition); J.base.scale.copy(a.departure.baseScale);
        this.fade(a, 1 - clamp01(t / FADE_MS));
      } else { this.fade(a, 1); a.departure = null; a.arriveAt = null; }
    }
  }

  // The slam (SPEC section 2a), age 0..300 ms with the hit at 150 (held there through hitstop): the hand rises overhead and out
  // so the shaft clears the swinger's own hat, a hop lands on the hit, the stick goes up and back to 2.25 rad and comes down in
  // the plane from the hand to the crown, and the hand slides up the shaft so the head lands on the crown.
  slamPose(a, crown, age, casting) {
    const J = a.J, M = J.mountWeapon, item = M.children[0];
    if (!item || casting) { a.slam = null; this.shoulder(a, 1, casting); return; }
    const lift = k01(age, 0, 90) * (1 - k01(age, 190, 300));
    J.handR.position.y += SLAM.raise * lift; J.handR.position.x -= SLAM.out * lift;
    J.base.position.y += SLAM.hop * Math.sin(Math.PI * k01(age, 60, 150));
    J.pivot.rotation.x += -0.25 * k01(age, 0, 90) * (1 - k01(age, 90, 140)) + SLAM.lean * k01(age, 110, 150) * (1 - k01(age, 190, 300));
    M.quaternion.copy(a.shoulderRest); M.position.copy(a.mountPosRest);
    a.h.object3d.updateMatrixWorld(true);
    const H = M.getWorldPosition(new THREE.Vector3()), P = new THREE.Vector3(crown.x, crown.y, crown.z);
    const hz = new THREE.Vector3(P.x - H.x, 0, P.z - H.z), hd = hz.length(), u = hz.divideScalar(hd || 1);
    const Lc = H.distanceTo(P), phiC = Math.atan2(P.y - H.y, hd), phiSh = Math.PI / 2 + 0.22;
    const phi = age < 90 ? phiSh + (SLAM.back - phiSh) * eOut(k01(age, 0, 90))
      : age < 150 ? SLAM.back + (phiC - SLAM.back) * eIn(k01(age, 90, 150))
      : phiC + (phiSh - phiC) * (1 - Math.pow(1 - k01(age, 150, 300), 2));
    const choke = Math.max(0, a.shaftTip - Lc) * (1 - k01(phi, phiC, SLAM.chokeBelow));
    const D = u.clone().multiplyScalar(Math.cos(phi)).addScaledVector(UP, Math.sin(phi)), n = new THREE.Vector3().crossVectors(u, UP).normalize();
    QS.setFromRotationMatrix(BX.makeBasis(n, D, new THREE.Vector3().crossVectors(n, D)));   // the item's world frame: shaft along D
    M.parent.getWorldQuaternion(PQ); a.h.object3d.getWorldQuaternion(RQ); IQ.copy(item.quaternion).invert();
    const parentInv = PQ.clone().invert();
    const slamQ = parentInv.clone().multiply(QS).multiply(IQ), shQ = parentInv.multiply(RQ.multiply(TILT)).multiply(IQ);
    const w = k01(age, 0, 50) * (1 - k01(age, 250, 300));
    M.quaternion.copy(shQ).slerp(slamQ, w);
    M.position.copy(M.parent.worldToLocal(H.clone().addScaledVector(D, -choke * w)));
    a.slam = { H, u, Lc, phi, phiC, age, w };
  }

  // The stick is shouldered between swings (no weapon inside a neighbour): the shaft (item local +y) points straight up in the
  // trenchie's own frame, tipped back and out, blended by `s` (1 shouldered, 0 the arm's own pose); a telegraph or a
  // signature holds it out. mount = parentWorld^-1 * rootWorld * tilt * itemLocal^-1 (final/SPEC.md section 2).
  // o.aim {x, z}: an attack's facing: where the stick goes when it leaves the shoulder (raised over every head, never out to the
  // side as the worn lean would send a 2.5x stick); o.upright 0..1: a shove stands it straight up; o.ko: the body spins and rolls
  // in its KO launch, so the stick keeps to the world's up and the body's heading alone (no sideways sweep through a neighbour).
  shoulder(a, s, casting, o = {}) {
    const M = a.J.mountWeapon; M.quaternion.copy(a.shoulderRest); M.position.copy(a.mountPosRest);
    if (casting) s = 0;
    if (!M.children.length || (s <= 0 && !o.aim)) return;
    const root = a.h.object3d; root.updateMatrixWorld(true);
    M.parent.getWorldQuaternion(PQ); IQ.copy(M.children[0].quaternion).invert();
    if (o.ko) RQ.setFromAxisAngle(UP, root.rotation.y); else root.getWorldQuaternion(RQ);
    const tilt = o.upright ? TILT.clone().slerp(NO_TURN, Math.min(1, o.upright)) : TILT;
    const parentInv = PQ.clone().invert(), shQ = parentInv.clone().multiply(RQ.multiply(tilt)).multiply(IQ);
    if (o.aim && s < 1) {
      // out toward the facing, raised so the shaft clears 1.5 tiles at 0.35 tile from the hand (above any neighbour's head)
      const H = M.getWorldPosition(new THREE.Vector3()), u = new THREE.Vector3(o.aim.x, 0, o.aim.z);
      if (u.lengthSq() < 1e-9) u.set(Math.sin(root.rotation.y), 0, Math.cos(root.rotation.y)); u.normalize();
      const th = Math.min(1.25, Math.max(0.35, Math.atan2(1.5 - H.y, 0.35)));
      const D = u.clone().multiplyScalar(Math.cos(th)).addScaledVector(UP, Math.sin(th)), n = new THREE.Vector3().crossVectors(u, UP).normalize();
      QS.setFromRotationMatrix(BX.makeBasis(n, D, new THREE.Vector3().crossVectors(n, D)));
      M.quaternion.copy(parentInv.multiply(QS).multiply(IQ)).slerp(shQ, Math.max(0, s));
      return;
    }
    M.quaternion.slerp(shQ, Math.min(1, s));
  }

  // The flash on this body's own materials: white emissive at 0.7, or its items' tier glow back when it ends.
  setFlash(a, v) {
    if (v === a.flashNow) return;
    a.flashNow = v;
    for (const m of a.bodyMeshes) { m.material.emissive.setRGB(v, v, v); m.material.emissiveIntensity = v ? FEEL.flashIntensity : 0; }
    if (v) for (const g of a.worn) g.traverse((m) => { if (m.isMesh && m.material.emissive) { m.material.emissive.setRGB(v, v, v); m.material.emissiveIntensity = FEEL.flashIntensity; } });
    else this.itemRenderer.restoreGlow(a.worn);
  }
}
