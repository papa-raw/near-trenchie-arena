// The trenchies: one three.js Group per fighter (W8), built by the approved B3 bodies (LOOK3.makeTrenchie), worn items riding
// the body's joints, and the motion that sells a fight, from the feel spec: anticipation drawn from the buffer's look-ahead,
// a walk locked to distance, per-body hitstop with vibration, hit shove and squash, the KO beat, bench and arrival.
// Everything here is render-only and a pure function of (events seen, render time): scrubbing or replaying reproduces it.
import * as THREE from 'three';
import { arenaTessellation } from './tessellation.mjs';
import { milliToWorld, angleToRotY, lerpAngle } from './frame.mjs';
import { TICK_MS } from './buffer.mjs';

export const BODY_SCALE = 2;                // the look3 body is 0.66 tall; the sim keeps bodies 1.3 tiles apart
const eOut = (k) => 1 - Math.pow(1 - Math.min(1, Math.max(0, k)), 3);
const eIn = (k) => Math.pow(Math.min(1, Math.max(0, k)), 3);
const clamp01 = (k) => Math.min(1, Math.max(0, k));
// closed-form damped spring from 0 to 1 (feel spec: playful k200 d12, default k170 d26)
function spring(t, k, d) {
  if (t <= 0) return 0;
  const w = Math.sqrt(k), z = d / (2 * w), wd = w * Math.sqrt(Math.max(1e-6, 1 - z * z));
  return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t));
}

// FEEL: one table (W11). Durations in ms, distances in the body's local units (1 local = 0.5 tile at BODY_SCALE 2).
export const FEEL = {
  anticipationMs: 150, anticipationShortMs: 100, strikeMs: 50, followMs: 220,
  hitstopLightMs: 50, hitstopHeavyMs: 100, hitstopKoMs: 200, crowdN: 4, crowdR: 3.0, crowdScale: 0.75, heavyHit: 18,
  squashMs: 160, shoveMs: 200, flashCap: 0.6,
  koFreezeMs: 200, koLaunchMs: 250, koHoldMs: 1000, arriveMs: 400,
  stepLenTiles: 1.0, bobLocal: 0.03, footSweepLocal: 0.07, footLiftLocal: 0.04,
};

const ITEM_FLASH_SETTLE_MS = 100; // LOOK3 clears its white hit flash after 90 ms
const PALETTE = ['p07', 'p09', 'p11', 'p14', 'p12', 'p08', 'p10', 'p15'];
function hashString(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

// A KITS.roster row for a fighter id; ids the roster does not know (anyone who snaps in) get a body colour from their id.
export function rosterRow(KITS, id, items) {
  const hit = [...(KITS.roster || []), ...(KITS.players || [])].find((r) => r.trenchieId === id);
  if (hit) return hit;
  const h = hashString(id);
  return { trenchieId: id, name: id, tag: id.length > 12 ? id.slice(0, 11) + '…' : id, paletteIds: [PALETTE[h % PALETTE.length], 'p04'], kit: items || {} };
}

class Actor {
  constructor(id, handle, row, scene) {
    this.id = id; this.h = handle; this.row = row; this.scene = scene;
    const J = handle.joints; this.J = J;
    this.baseScaleY = J.base.scale.y;
    this.def = { hand: J.handR.position.clone(), handL: J.handL.position.clone(), footL: J.footL.position.clone(), footR: J.footR.position.clone(), pivot: J.pivot.position.clone() };
    this.phi = 0; this.px = null; this.pz = null; this.speed = 0;
    this.anims = [];                 // {kind, tick, ...} fired from events; evaluated against the render tick
    this.freezeUntil = 0; this.freezeFrom = 0;
    this.hpMax = 100; this.lastAlive = null;
    this.koAt = null; this.koTick = null; this.arriveAt = null;
    this.blinkAt = 2500 + (hashString(id) % 3000); this.blinkEnd = 0;
    this.glowRestoreAt = 0; this.face = 'normal'; this.items = null; this.worn = []; this.shieldMesh = null;
    this.hitDir = { x: 0, z: 0 };
  }
}

export class Actors {
  constructor(scene, LOOK3, KITS, itemRenderer, { arenaQuality = false } = {}) {
    this.scene = scene; this.LOOK3 = LOOK3; this.KITS = KITS; this.itemRenderer = itemRenderer; this.map = new Map();
    this.arenaQuality = arenaQuality; itemRenderer.arenaQuality = arenaQuality;
    this.crowd = new Map();         // id -> number of live bodies within crowdR (hitstop scale)
  }

  get(id) { return this.map.get(id); }

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
    return a;
  }

  setItems(a, f) {
    const key = JSON.stringify(f.items);
    if (a.items === key) return;
    a.items = key;
    this.itemRenderer.clear(a.h);
    a.worn = this.itemRenderer.equip(a.h, f.items);
    a.casts = null;
  }

  // ---- events fired from the buffer ------------------------------------------------------------------------------------
  onAttack(ev, tick, ownerState) { // called early (look-ahead) so the wind-up can be drawn before the strike
    const a = this.map.get(ev.fighter); if (!a) return;
    a.anims.push({ kind: 'attack', tick, weapon: ev.weapon, dirx: ownerState ? ownerState.dx : 0, dirz: ownerState ? ownerState.dz : 0 });
  }
  onHit(ev, tick, nowMs, srcPos, dstPos) {
    const a = this.map.get(ev.target); if (!a) return;
    const heavy = ev.damage >= FEEL.heavyHit;
    const crowd = (this.crowd.get(ev.target) || 0) >= FEEL.crowdN ? FEEL.crowdScale : 1;
    const ms = (heavy ? FEEL.hitstopHeavyMs : FEEL.hitstopLightMs) * crowd;
    a.freezeFrom = nowMs; a.freezeUntil = nowMs + ms;
    let dx = 0, dz = 0;
    if (srcPos && dstPos) { dx = dstPos.x - srcPos.x; dz = dstPos.z - srcPos.z; const L = Math.hypot(dx, dz) || 1; dx /= L; dz /= L; }
    a.anims.push({ kind: 'hit', tick, dmg: ev.damage, dx, dz, heavy, startMs: nowMs });
    a.h.flash(); a.glowRestoreAt = nowMs + ITEM_FLASH_SETTLE_MS;
    if (heavy) a.anims.push({ kind: 'hurtface', tick, startMs: nowMs });
    // the striker freezes for 0.6 of the victim's
    const s = this.map.get(ev.source); if (s && s !== a) { s.freezeFrom = nowMs; s.freezeUntil = Math.max(s.freezeUntil, nowMs + ms * 0.6); }
  }
  onKo(ev, tick, nowMs) {
    const a = this.map.get(ev.fighter); if (!a) return;
    a.koAt = nowMs; a.koTick = tick; a.freezeFrom = nowMs; a.freezeUntil = nowMs + FEEL.hitstopKoMs;
    a.h.flash(); a.glowRestoreAt = nowMs + ITEM_FLASH_SETTLE_MS;
    const s = ev.source && this.map.get(ev.source); if (s && s !== a) { s.freezeFrom = nowMs; s.freezeUntil = nowMs + FEEL.hitstopKoMs * 0.6; }
  }
  // a new life drops in; delayMs holds the drop (the pre-jump card stamps first, prejump.mjs) with the body out of sight
  onRespawn(ev, tick, nowMs, delayMs = 0) { const a = this.map.get(ev.fighter); if (a) { a.arriveAt = nowMs + delayMs; a.koAt = null; } }

  // ---- one frame -------------------------------------------------------------------------------------------------------
  // fighters: [{id, x, y (milli), dir (deg), status, hp, shield, items, itemRows}] interpolated for this frame
  update(fighters, renderTick, nowMs, dtMs, bench) {
    const live = fighters.filter((f) => f.status === 0);
    // crowd density for hitstop scale
    for (const f of live) { let n = 0; for (const g of live) if (Math.hypot(f.x - g.x, f.y - g.y) / 1000 <= FEEL.crowdR) n++; this.crowd.set(f.id, n); }

    const out = new Map();
    for (const f of fighters) {
      const a = this.ensure(f);
      this.setItems(a, f);
      if (nowMs >= a.glowRestoreAt) this.itemRenderer.restoreGlow(a.worn);
      a.hpMax = Math.max(a.hpMax, f.hp);
      const o = a.h.object3d;
      let x = f.x, y = f.y, dir = f.dir, state = 'alive';
      if (f.status === 0) a.lastAlive = { x, y, dir };
      else {
        const sinceKo = a.koAt === null ? Infinity : nowMs - a.koAt;
        if (a.lastAlive && sinceKo < FEEL.koFreezeMs + FEEL.koLaunchMs + FEEL.koHoldMs) { x = a.lastAlive.x; y = a.lastAlive.y; dir = a.lastAlive.dir; state = 'ko'; }
        else { const seat = bench.get(f.id); if (seat) { x = seat.x; y = seat.y; dir = seat.dir; } state = 'bench'; }
      }
      const w = milliToWorld(x, y);
      o.position.set(w.x, 0, w.z);
      o.visible = f.status !== 2 && !(f.status === 0 && a.arriveAt !== null && nowMs < a.arriveAt);   // a held drop: not in sight yet
      out.set(f.id, { x: w.x, z: w.z, state, f });
      this.pose(a, f, state, w, dir, renderTick, nowMs, dtMs);
      a.J.base.scale.y *= a.baseScaleY;
      out.get(f.id).lift = a.J.base.position.y * BODY_SCALE; // a body dropping in or knocked up: its tag follows it
    }
    // drop actors whose fighter left the snapshot
    for (const [id, a] of this.map) if (!out.has(id)) { this.scene.remove(a.h.object3d); a.h.dispose(); this.map.delete(id); }
    return out;
  }

  pose(a, f, state, w, dir, rt, now, dt) {
    const J = a.J, o = a.h.object3d;
    // reset the joints this module drives
    J.base.scale.set(1, 1, 1); J.base.position.set(0, 0, 0); J.pivot.position.copy(a.def.pivot); J.pivot.rotation.set(0, 0, 0);
    J.handR.position.copy(a.def.hand); J.handL.position.copy(a.def.handL); J.footL.position.copy(a.def.footL); J.footR.position.copy(a.def.footR);
    o.scale.setScalar(BODY_SCALE);
    o.rotation.y = angleToRotY(dir);
    // bodies waiting on the shore cast no shadow: the ring holds 4 to 6, so most of the 14 are idle (budget lever)
    const casts = state !== 'bench';
    if (a.casts !== casts) { a.casts = casts; o.traverse((m) => { if (m.isMesh && m.name !== 'shadow') m.castShadow = casts; }); }

    const frozen = now < a.freezeUntil && state === 'alive';
    if (frozen) { // hitstop: the pose holds and trembles; the body's position keeps following the stream
      const left = (a.freezeUntil - now) / Math.max(1, a.freezeUntil - a.freezeFrom);
      J.pivot.position.x += (Math.floor(now / 16) % 2 ? 1 : -1) * 0.03 * left;
      return;
    }

    // walk, locked to distance: the step phase advances by tiles moved, never by time
    if (a.px !== null && state === 'alive') {
      const moved = Math.hypot(w.x - a.px, w.z - a.pz);
      if (moved < 1.5) a.phi += moved / FEEL.stepLenTiles;
      a.speed = dt > 0 ? (moved / dt) * 1000 : a.speed; // tiles per second
    }
    a.px = w.x; a.pz = w.z;
    const moving = state === 'alive' && a.speed > 0.4, sw = Math.min(1, a.speed / 3);
    const ph = a.phi * Math.PI;
    if (moving) {
      J.base.position.y = Math.abs(Math.sin(ph)) * FEEL.bobLocal * sw;
      const s = Math.sin(ph) * FEEL.footSweepLocal * sw;
      J.footL.position.z += s; J.footR.position.z -= s;
      J.footL.position.y += Math.max(0, Math.cos(ph)) * FEEL.footLiftLocal * sw; J.footR.position.y += Math.max(0, -Math.cos(ph)) * FEEL.footLiftLocal * sw;
      J.handL.position.z -= s * 0.8; J.pivot.rotation.x += 0.08 * sw;
    } else if (state === 'alive') {
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
    for (let i = a.anims.length - 1; i >= 0; i--) {
      const m = a.anims[i], u = (rt - m.tick) * TICK_MS; // ms relative to the event's tick
      if (m.kind === 'attack') {
        const short = m.weapon === 'shot' || m.weapon === 'zap';
        const lead = short ? FEEL.anticipationShortMs : FEEL.anticipationMs;
        if (u > FEEL.strikeMs + FEEL.followMs) { a.anims.splice(i, 1); continue; }
        let reach = 0, lean = 0, rise = 0;
        if (u < -lead) continue;
        if (u < 0) { const k = eIn((u + lead) / lead); reach = -0.10 * k; lean = -0.14 * k; rise = 0.03 * k; }       // pull back, away from the target
        else if (u < FEEL.strikeMs) { const k = eOut(u / FEEL.strikeMs); reach = -0.10 + 0.34 * k; lean = -0.14 + 0.34 * k; rise = 0.03 * (1 - k); } // strike
        else { const k = spring((u - FEEL.strikeMs) / 1000, 200, 12); reach = 0.24 * (1 - k); lean = 0.20 * (1 - spring((u - FEEL.strikeMs) / 1000, 170, 26)); }  // follow-through on the playful spring
        J.handR.position.z += reach; J.handR.position.y += rise; J.pivot.rotation.x += lean;
        if (m.weapon === 'lunge' && u >= 0 && u < 250) J.pivot.position.z += 0.14 * Math.sin(Math.PI * clamp01(u / 250));
      } else if (m.kind === 'hit') {
        const u2 = now - m.startMs; if (u2 > FEEL.shoveMs + 40) { a.anims.splice(i, 1); continue; }
        const dist = Math.min(0.30, 0.10 + 0.0075 * m.dmg) * 0.5, k = u2 < 60 ? eOut(u2 / 60) : 1 - eOut((u2 - 60) / (FEEL.shoveMs - 60));
        const L = toLocal(m.dx, m.dz); J.base.position.x += L.x * dist * k; J.base.position.z += L.z * dist * k;
        J.pivot.rotation.x += -L.z * 0.16 * k; J.pivot.rotation.z += L.x * 0.16 * k;
        const sq = (u2 < 40 ? eOut(u2 / 40) : 1 - eOut((u2 - 40) / (FEEL.squashMs - 40))) * (m.heavy ? 0.14 : 0.1);
        J.base.scale.set(J.base.scale.x * (1 + sq * 0.9), J.base.scale.y * (1 - sq), J.base.scale.z * (1 + sq * 0.9));
      } else if (m.kind === 'hurtface') { if (now - m.startMs < 200) face = 'hurt'; else a.anims.splice(i, 1); }
    }

    // KO beat (feel row 10): freeze + flash, launch up and roll back, hold, then to the bench
    if (state === 'ko') {
      const t = now - a.koAt;
      if (t < FEEL.koFreezeMs) { J.pivot.position.x += (Math.floor(now / 16) % 2 ? 1 : -1) * 0.025; face = 'hurt'; }
      else {
        const k = clamp01((t - FEEL.koFreezeMs) / FEEL.koLaunchMs);
        J.base.position.y = Math.sin(Math.PI * k) * 0.32 * (1 - k * 0.2);
        J.pivot.rotation.x = -eOut(k) * 1.55; face = 'ko';
      }
    } else if (state === 'bench') {
      o.scale.setScalar(BODY_SCALE * 0.9); // waiting on the shore: idle, facing the ring
    }
    if (state === 'alive' && a.arriveAt !== null) { // respawn: a short drop with a landing
      const t = now - a.arriveAt;
      if (t > FEEL.arriveMs) a.arriveAt = null;
      else if (t < 0) J.base.position.y = 1.4;   // held above the drop point until the drop starts
      else if (t < 200) { J.base.position.y = (1 - eIn(t / 200)) * 1.4; J.base.scale.y = 1.1; J.base.scale.x = J.base.scale.z = 0.94; }
      else { const k = (t - 200) / 200, sq = Math.sin(Math.PI * k) * (1 - k) * 0.22; J.base.scale.set(1 + sq, 1 - sq * 1.2, 1 + sq); }
    }
    if (face !== a.face) { a.h.setFace(face); a.face = face; }

    // spawn / signature shield: a pale bubble
    if (f.shield > 0 && state === 'alive') {
      if (!a.shieldMesh) { a.shieldMesh = new THREE.Mesh(new THREE.SphereGeometry(0.62, 20, 14), new THREE.MeshBasicMaterial({ color: '#D3F1E6', transparent: true, opacity: 0.28, depthWrite: false })); a.shieldMesh.position.y = 0.4; J.root.add(a.shieldMesh); }
      a.shieldMesh.visible = true; a.shieldMesh.scale.setScalar(1 + 0.04 * Math.sin(now / 120));
    } else if (a.shieldMesh) a.shieldMesh.visible = false;
  }
}
