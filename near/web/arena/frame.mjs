// The frame contract (W9): the one place that maps the sim's integer milli-tiles to three.js world units and back.
//
//   sim     x east, y south, integer milli-tiles, origin = arena centre; angles are integer degrees, 0 = +x, clockwise seen
//           from above (so 90 = +y = south).
//   world   1 unit = 1 tile, y up. sim (x, y) -> world (x / 1000, h, y / 1000): sim x is world x, sim y is world z.
//   facing  a model whose front is local +z turns by rotation.y = PI/2 - angle, which sends +z to (cos a, 0, sin a).
//
// Pure math, no three.js import, so the same file runs in the page and in the node test.

export const MILLI = 1000;
export const ARENA_RADIUS_MILLI = 12000;

export const milliToWorld = (x, y, h = 0) => ({ x: x / MILLI, y: h, z: y / MILLI });
export const worldToMilli = (wx, wz) => ({ x: Math.round(wx * MILLI), y: Math.round(wz * MILLI) });

const DEG = Math.PI / 180;
export const angleToRotY = (deg) => Math.PI / 2 - deg * DEG;
export const rotYToAngle = (rotY) => ((Math.round((Math.PI / 2 - rotY) / DEG) % 360) + 360) % 360;

// Shortest signed turn from degrees a to degrees b, so interpolated facing never spins the long way round.
export const angleDelta = (a, b) => ((((b - a) % 360) + 540) % 360) - 180;
export const lerpAngle = (a, b, k) => a + angleDelta(a, b) * k;

// Picking: the sim point under a screen point. `ndc` is (-1..1, -1..1, y up). `camera` is an OrthographicCamera that has had
// updateMatrixWorld() called (we read its matrixWorld elements and frustum, nothing else). The ray runs along the camera's
// forward axis from the point on the near plane; it meets the ground plane y = 0.
export function pickMilli(ndcX, ndcY, camera) {
  const e = camera.matrixWorld.elements, z = camera.zoom || 1;
  const vx = (camera.left + camera.right) / 2 / z + ndcX * (camera.right - camera.left) / 2 / z;
  const vy = (camera.top + camera.bottom) / 2 / z + ndcY * (camera.top - camera.bottom) / 2 / z;
  const vz = -camera.near;
  // view -> world (column-major matrix)
  const ox = e[0] * vx + e[4] * vy + e[8] * vz + e[12];
  const oy = e[1] * vx + e[5] * vy + e[9] * vz + e[13];
  const oz = e[2] * vx + e[6] * vy + e[10] * vz + e[14];
  const dx = -e[8], dy = -e[9], dz = -e[10]; // forward = -z of the camera
  if (Math.abs(dy) < 1e-9) return null;
  const t = -oy / dy;
  return worldToMilli(ox + dx * t, oz + dz * t);
}

// The reverse, for tests and for HUD anchors: world point -> ndc through an orthographic camera.
export function projectNdc(wx, wy, wz, camera) {
  const e = camera.matrixWorld.elements, z = camera.zoom || 1;
  // world -> view: the inverse of a rigid transform (rotation transposed)
  const px = wx - e[12], py = wy - e[13], pz = wz - e[14];
  const vx = e[0] * px + e[1] * py + e[2] * pz;
  const vy = e[4] * px + e[5] * py + e[6] * pz;
  const nx = (vx - (camera.left + camera.right) / 2 / z) / ((camera.right - camera.left) / 2 / z);
  const ny = (vy - (camera.top + camera.bottom) / 2 / z) / ((camera.top - camera.bottom) / 2 / z);
  return { x: nx, y: ny };
}
