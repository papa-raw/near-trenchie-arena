// A recorded snapshot stream, fed through the same buffer as live spectators. Stress projection changes only the view.
import * as THREE from 'three';
import { decode } from './codec.mjs';
import { TICK_MS } from './buffer.mjs';

export class BudgetReplay {
  constructor(record, buffer, { crowd = 0, onMetadata = () => {} } = {}) {
    this.onMetadata = onMetadata; this.metadataIndex = 0;
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
      this.buffer.push(snap, this.start + this.index * TICK_MS); this.index++;
    }
  }
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
