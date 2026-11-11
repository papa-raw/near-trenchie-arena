// A recorded snapshot stream, fed through the same buffer as live spectators. Stress projection changes only the view.
import * as THREE from 'three';
import { decode } from './codec.mjs';
import { TICK_MS } from './buffer.mjs';

export class BudgetReplay {
  constructor(record, buffer, { crowd = 0, teleN = 0, onMetadata = () => {} } = {}) {
    this.onMetadata = onMetadata; this.metadataIndex = 0; this.teleN = teleN;
    this.record = record; this.buffer = buffer; this.crowd = crowd; this.start = null; this.index = 0;
  }
  pump(now) {
    if (this.start === null) this.start = now;
    const target = Math.min(this.record.frames.length - 1, Math.floor((now - this.start) / TICK_MS));
    while (this.index <= target) {
      const snap = decode(this.record.frames[this.index]);
      const messages = this.record.metadata || [];
      while (this.metadataIndex < messages.length && messages[this.metadataIndex].tick <= snap.tick) this.onMetadata(messages[this.metadataIndex++]);
      // All sixteen stay visible with a complete kit throughout the controlled render stress recording.
      snap.fighters = snap.fighters.map((f, i) => {
        const angle = (i * 137.5 + this.crowd * 61) * Math.PI / 180, r = this.crowd && i < 10 ? 1100 : 6500 + 700 * Math.sin(snap.tick / 40 + i);
        return { ...f, x: Math.round(Math.cos(angle) * r), y: Math.round(Math.sin(angle) * r), dir: (snap.tick + i * 29) % 360, status: 0, hp: Math.max(1, f.hp), items: this.record.loadouts[f.id], itemRows: Object.values(this.record.loadouts[f.id]).map((id) => snap.rows.indexOf(id)) };
      });
      // Preserve the recorded stream's events, but avoid synthetic KO/respawn hiding bodies in the fixed-density view.
      snap.events = snap.events.filter((e) => e.kind !== 'ko' && e.kind !== 'respawn');
      if (this.teleN) snap.objects = snap.objects.concat(stressTelegraphs(this.teleN, snap.tick));
      this.buffer.push(snap, this.start + this.index * TICK_MS); this.index++;
    }
  }
}

export const STRESS_TELE_TICKS = 40;   // each stress telegraph lives 2 s, then a fresh one replaces it (create/dispose churn)
/** At least `n` extra live telegraphs for the budget scene (&tele_n=n): lobbed circles of 1.2 to 4 tiles (the most candles)
 * and beam lines, spread over the ring, staggered so they start and land at different ticks. View-only stress: the sim and
 * the recording are untouched. */
export function stressTelegraphs(n, tick) {
  const out = [];
  for (let j = 0; j < n; j++) {
    const phase = Math.floor((j * STRESS_TELE_TICKS) / n), cycle = Math.floor((tick + phase) / STRESS_TELE_TICKS);
    const resolveAt = cycle * STRESS_TELE_TICKS - phase + STRESS_TELE_TICKS, key = 'stress-tele-' + j + '-' + cycle;
    const a = j * 2.399, r = 2500 + (j % 5) * 1000, x = Math.round(Math.cos(a) * r), y = Math.round(Math.sin(a) * r);
    if (j % 3 === 2) out.push({ key, kind: 'beam', x, y, angle: (j * 47) % 360, range: 4500, width: 700, resolveAt });
    else out.push({ key, kind: 'lob', x: 0, y: 0, tx: x, ty: y, radius: 1200 + (j % 4) * 933, resolveAt });
  }
  return out;
}

/** The same spark geometry/material as the arena effects, held at the prescribed 150 live shapes. */
export function budgetEffects(scene) {
  const group = new THREE.Group(); group.name = 'budget-effects';
  for (let i = 0; i < 150; i++) {
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(.16, 0), new THREE.MeshBasicMaterial({ color: '#FFF8EA', transparent: true, opacity: .7 }));
    m.castShadow = false; m.position.set(Math.cos(i * 2.4) * (2 + i % 9), .5 + i % 4 * .2, Math.sin(i * 2.4) * (2 + i % 9)); group.add(m);
  }
  scene.add(group); return group;
}
