// Render-only instancing. Source meshes remain under their actor joints; instances copy their world transforms.
import * as THREE from 'three';
const hashArray = (array) => { const bytes = new Uint8Array(array.buffer, array.byteOffset, array.byteLength); let h = 2166136261; for (const b of bytes) { h ^= b; h = Math.imul(h, 16777619); } return (h >>> 0).toString(16); };
export class ActorInstances {
  constructor(scene) { this.scene = scene; this.geometryKeys = new WeakMap(); this.batches = new Map(); }
  geometryKey(g) {
    if (!this.geometryKeys.has(g)) {
      const key = Object.entries(g.attributes).sort(([a], [b]) => a.localeCompare(b)).map(([k, a]) => [k, a.itemSize, a.normalized, a.count, hashArray(a.array)].join(':'));
      this.geometryKeys.set(g, key.join('|') + '|i:' + (g.index ? hashArray(g.index.array) : '-'));
    }
    return this.geometryKeys.get(g);
  }
  key(o) {
    const m = o.material;
    return [this.geometryKey(o.geometry), m.type, m.side, m.transparent, m.opacity, m.alphaTest, m.depthWrite, m.depthTest, m.vertexColors,
      m.map?.uuid, m.gradientMap?.uuid, m.emissive?.getHexString(), m.emissiveIntensity, o.castShadow, o.receiveShadow, o.renderOrder].join(';');
  }
  sync(actors) {
    const buckets = new Map(); this.scene.updateMatrixWorld(true);
    for (const actor of actors.map.values()) actor.h.object3d.traverseVisible((o) => {
      if (!o.isMesh || Array.isArray(o.material)) return;
      // Actor source geometry is kept for ownership, disposal and flash; only layer zero renders.
      o.layers.set(0);
      const key = this.key(o);
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(o);
    });
    for (const [key, sources] of buckets) {
      if (sources.length < 2) continue;
      let batch = this.batches.get(key);
      if (!batch || batch.capacity < sources.length) {
        if (batch) this.release(batch);
        const first = sources[0], material = first.material.clone(); material.color.set('#FFFFFF');
        const capacity = 2 ** Math.ceil(Math.log2(sources.length));
        const mesh = new THREE.InstancedMesh(first.geometry.clone(), material, capacity);
        mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage); mesh.frustumCulled = false;
        mesh.castShadow = first.castShadow; mesh.receiveShadow = first.receiveShadow; mesh.renderOrder = first.renderOrder;
        mesh.name = 'actor-instances'; this.scene.add(mesh); batch = { mesh, capacity }; this.batches.set(key, batch);
      }
      batch.mesh.count = sources.length;
      sources.forEach((o, i) => { o.layers.set(1); batch.mesh.setMatrixAt(i, o.matrixWorld); batch.mesh.setColorAt(i, o.material.color); });
      batch.mesh.instanceMatrix.needsUpdate = true; batch.mesh.instanceColor.needsUpdate = true;
    }
    for (const [key, batch] of this.batches) if ((buckets.get(key)?.length || 0) < 2) { this.release(batch); this.batches.delete(key); }
  }
  release({ mesh }) { this.scene.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); mesh.dispose(); }
  dispose() { for (const batch of this.batches.values()) this.release(batch); this.batches.clear(); }
}
