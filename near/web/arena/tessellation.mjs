// Arena-only grid sampling: retain the authored positions, normals, fit, UVs and colours. Cards use original geometry.
import * as THREE from 'three';
const samples = (n, limit) => { const count = Math.min(n, limit); return Array.from({ length: count + 1 }, (_, i) => Math.round(i * n / count)); };
function gridGeometry(source, rows, cols, rowLimit, colLimit) {
  const rr = samples(rows, rowLimit), cc = samples(cols, colLimit), geometry = new THREE.BufferGeometry();
  for (const [name, attr] of Object.entries(source.attributes)) {
    const data = new attr.array.constructor(rr.length * cc.length * attr.itemSize); let at = 0;
    for (const r of rr) for (const c of cc) for (let k = 0; k < attr.itemSize; k++) data[at++] = attr.array[((cols + 1) * r + c) * attr.itemSize + k];
    geometry.setAttribute(name, new THREE.BufferAttribute(data, attr.itemSize, attr.normalized));
  }
  const indices = [], p = geometry.attributes.position, n = geometry.attributes.normal;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), cross = new THREE.Vector3(), normal = new THREE.Vector3();
  function triangle(i, j, k) {
    a.fromBufferAttribute(p, i); b.fromBufferAttribute(p, j); c.fromBufferAttribute(p, k);
    cross.crossVectors(b.sub(a), c.sub(a)); if (cross.lengthSq() < 1e-18) return;
    normal.fromBufferAttribute(n, i).add(new THREE.Vector3().fromBufferAttribute(n, j)).add(new THREE.Vector3().fromBufferAttribute(n, k));
    if (cross.dot(normal) < 0) indices.push(i, k, j); else indices.push(i, j, k);
  }
  for (let r = 0; r < rr.length - 1; r++) for (let col = 0; col < cc.length - 1; col++) {
    const i = r * cc.length + col, j = i + 1, k = i + cc.length, l = k + 1; triangle(i, k, j); triangle(j, k, l);
  }
  geometry.setIndex(indices); geometry.userData.arenaSampled = true; return geometry;
}
/** Reduce only smooth parametric grids. Tiny badges use fewer samples than the body and hats seen in the follow inset. */
export function arenaTessellation(root) {
  root.updateWorldMatrix(true, true);
  root.traverse((mesh) => {
    if (!mesh.isMesh || mesh.geometry.userData.arenaSampled) return;
    const g = mesh.geometry, p = g.parameters; if (!p) return;
    g.computeBoundingSphere();
    const scale = new THREE.Vector3(); mesh.getWorldScale(scale);
    // World radius .22 tiles: roughly 7 px at the desktop arena zoom; keep extra segments for larger silhouettes.
    const large = g.boundingSphere.radius * Math.max(scale.x, scale.y, scale.z) >= .22;
    let replacement;
    if (g.type === 'SphereGeometry') replacement = gridGeometry(g, p.heightSegments, p.widthSegments, large ? 14 : 10, large ? 24 : 16);
    else if (g.type === 'LatheGeometry') replacement = gridGeometry(g, p.segments, p.points.length - 1, 28, 22);
    else if (g.type === 'TorusGeometry') replacement = gridGeometry(g, p.radialSegments, p.tubularSegments, large ? 8 : 6, large ? 28 : 20);
    else if (g.type === 'TubeGeometry') replacement = gridGeometry(g, p.tubularSegments, p.radialSegments, 20, 6);
    if (replacement) { mesh.geometry = replacement; g.dispose(); }
  });
}
