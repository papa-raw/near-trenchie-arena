// Bake a static item's primitive tree into one vertex-coloured mesh per material kind. Fit first; joints remain outside it.
import * as THREE from 'three';
export function mergeItem(group) {
  if (group.userData.merged) return;
  group.updateWorldMatrix(true, true);
  const inverse = group.matrixWorld.clone().invert(), buckets = new Map(), originals = [];
  group.traverse((o) => {
    if (!o.isMesh || Array.isArray(o.material) || o.material.map) return;
    const m = o.material, key = [m.type, m.transparent, m.opacity, m.side, m.emissive?.getHexString(), m.emissiveIntensity, m.depthWrite, m.depthTest, o.castShadow, o.receiveShadow].join('|');
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(o); originals.push(o);
  });
  for (const meshes of buckets.values()) {
    const pos = [], normal = [], colors = [], uv = [];
    for (const mesh of meshes) {
      const geo = mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone();
      geo.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inverse, mesh.matrixWorld));
      if (!geo.attributes.normal) geo.computeVertexNormals();
      const p = geo.attributes.position, n = geo.attributes.normal, vc = geo.attributes.color, tex = geo.attributes.uv, color = mesh.material.color;
      for (let i = 0; i < p.count; i++) {
        pos.push(p.getX(i), p.getY(i), p.getZ(i)); normal.push(n.getX(i), n.getY(i), n.getZ(i));
        colors.push(color.r * (vc ? vc.getX(i) : 1), color.g * (vc ? vc.getY(i) : 1), color.b * (vc ? vc.getZ(i) : 1));
        uv.push(tex ? tex.getX(i) : 0, tex ? tex.getY(i) : 0);
      }
      geo.dispose();
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normal, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3)); geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    const first = meshes[0], material = first.material.clone(); material.color.set('#FFFFFF'); material.vertexColors = true;
    if (first.material.userData.tierGlow) material.userData.tierGlow = first.material.userData.tierGlow.clone();
    const mesh = new THREE.Mesh(geometry, material); mesh.name = 'item-merged'; mesh.castShadow = first.castShadow; mesh.receiveShadow = first.receiveShadow; group.add(mesh);
  }
  const materials = new Set(), geometries = new Set();
  for (const mesh of originals) { mesh.parent.remove(mesh); geometries.add(mesh.geometry); materials.add(mesh.material); }
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
  group.userData.merged = true;
}
