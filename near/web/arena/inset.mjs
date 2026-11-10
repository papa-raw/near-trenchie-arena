// The follow inset (F19): click any trenchie and a second, closer view of it opens in a corner. No login, render-only: it is
// the same scene drawn again from a camera that follows the body (scissored into the box), so it costs one more pass only
// while it is open. Click the same body, the close mark, or an empty spot of sand to close it.
import * as THREE from 'three';
import { AZ_DEG } from './scene.mjs';
export { PICK_PX, pickFighter } from './pick.mjs';

export const INSET_PPT = 72;         // pixels per tile inside the inset

export class Inset {
  constructor({ stage, root, tagOf }) {
    this.stage = stage; this.followId = null; this.tagOf = tagOf;
    this.box = document.createElement('div'); this.box.className = 'inset'; this.box.hidden = true;
    this.cap = document.createElement('div'); this.cap.className = 'cap'; this.box.appendChild(this.cap);
    this.close = document.createElement('button'); this.close.type = 'button'; this.close.className = 'x'; this.close.textContent = '×'; this.close.setAttribute('aria-label', 'Close the follow view'); this.close.onclick = () => this.clear();
    this.box.appendChild(this.close); document.body.appendChild(this.box);
    this.cam = new THREE.OrthographicCamera(-4, 4, 3, -3, 0.1, 200);
  }
  follow(id) { this.followId = id === this.followId ? null : id; this.box.hidden = this.followId === null; }
  clear() { this.followId = null; this.box.hidden = true; }

  // draw after the main pass; `centre` is the world point of the followed body
  render(centre) {
    if (this.followId === null || !centre) return;
    const { renderer, scene, view } = this.stage, r = this.box.getBoundingClientRect(), w = r.width, h = r.height;
    if (w < 40 || h < 40) return;
    this.cap.textContent = this.tagOf(this.followId);
    const e = 35.264 * Math.PI / 180, az = AZ_DEG * Math.PI / 180, dir = new THREE.Vector3(Math.sin(az) * Math.cos(e), Math.sin(e), Math.cos(az) * Math.cos(e));
    const c = this.cam; c.left = -w / 2 / INSET_PPT; c.right = w / 2 / INSET_PPT; c.top = h / 2 / INSET_PPT; c.bottom = -h / 2 / INSET_PPT; c.updateProjectionMatrix();
    const target = new THREE.Vector3(centre.x, 0.8, centre.z); c.position.copy(target).addScaledVector(dir, 60); c.up.set(0, 1, 0); c.lookAt(target); c.updateMatrixWorld();
    renderer.setScissorTest(true); renderer.setScissor(r.left, view.h - r.bottom, w, h); renderer.setViewport(r.left, view.h - r.bottom, w, h);
    renderer.render(scene, c);
    renderer.setScissorTest(false); renderer.setViewport(0, 0, view.w, view.h);
  }
}
