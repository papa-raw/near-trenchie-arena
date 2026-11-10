// Renderer-neutral item adapter shared by the arena and card stills. Geometry and fit come from the approved kit.
import * as THREE from 'three';
import { arenaTessellation } from './arena/tessellation.mjs';
import { mergeItem } from './arena/item-merge.mjs';
import { LOOK3 } from './art/look3.js';
import { buildSpec, wear, onFloor } from './art/kit3d.js';

export const TIER_GLOW = Object.freeze({ common: '#A3A9B2', rare: '#6FA3D6', legendary: '#F7CF6B' });
const TIER_EMISSION = 0.18; // subtle tier tint; the approved toon palette remains the surface colour
const MOUNTS = ['mountWeapon', 'mountHead', 'mountBody', 'mountTrinket', 'mountBack'];

async function readJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error('Item assets: ' + response.status + ' at ' + url + '; serve the near directory, including items/');
  return response.json();
}

/** Load the published kit and its specs once. Rare rows share their common geometry and keep their own tier. */
export async function loadItems(records, base = new URL('../items/', import.meta.url)) {
  const kit = await readJSON(new URL('kit.json', base));
  const ids = [...new Set(Object.keys(records).filter((id) => !id.startsWith('sig-')).map((id) => id.replace(/^r-/, 'c-')))];
  const specs = Object.fromEntries(await Promise.all(ids.map(async (id) => [id, await readJSON(new URL('specs/' + id + '.json', base))])));
  return new ItemRenderer(kit, specs, records);
}

export class ItemRenderer {
  constructor(kit, specs, records) { this.kit = kit; this.specs = specs; this.records = records; this.warned = new Set(); }

  /** A single ItemSpec, in item units. No renderer instructions are read from item data. */
  buildSpec(spec) {
    const g = buildSpec(this.kit, spec);
    g.userData.itemRow = spec.id; g.userData.slot = spec.slot; g.userData.tier = spec.tier;
    // One fixed three-band toon material per palette colour in an item, including its renderer-owned tier tint.
    const materials = new Map(), old = new Set();
    g.traverse((m) => {
      if (!m.isMesh) return;
      old.add(m.material); const key = m.material.color.getHexString();
      if (!materials.has(key)) {
        const mat = m.material.clone(); mat.side = THREE.DoubleSide;
        mat.emissive.set(TIER_GLOW[spec.tier] || TIER_GLOW.common); mat.emissiveIntensity = TIER_EMISSION;
        mat.userData.tierGlow = mat.emissive.clone(); materials.set(key, mat);
      }
      m.material = materials.get(key);
    });
    old.forEach((m) => m.dispose()); return g;
  }

  placeholder(id, slot, error) {
    if (!this.warned.has(id)) { this.warned.add(id); console.warn('Item renderer: ' + error + '; showing placeholder for ' + id); }
    const g = new THREE.Group(); g.name = 'Unknown item';
    g.userData = { itemRow: id, slot: slot || 'trinket', tier: 'common', placeholder: true, label: 'Unknown item' };
    const mesh = new THREE.Mesh(new THREE.OctahedronGeometry(.08), new THREE.MeshToonMaterial({ color: '#A3A9B2' }));
    mesh.name = 'Unknown item'; g.add(mesh); return g;
  }

  build(id, slot) {
    try { return this.buildKnown(id); }
    catch (error) { return this.placeholder(id, slot || this.records[id]?.slot, error.message); }
  }

  buildKnown(id) {
    const row = this.records[id];
    if (!row) throw new Error('Item renderer: unknown catalog row ' + id);
    // Signature clothes belong to the approved house likeness, with their existing named drawing; they have no ItemSpec.
    if (id.startsWith('sig-')) {
      const g = LOOK3.makeItem(id, 'worn', { slot: row.slot });
      g.userData.itemRow = id; g.userData.slot = row.slot; g.userData.tier = row.tier; g.userData.signatureClothes = true; return g;
    }
    const source = this.specs[id.replace(/^r-/, 'c-')];
    if (!source) throw new Error('Item renderer: missing spec for ' + id);
    return this.buildSpec({ ...source, id, tier: row.tier, slot: row.slot });
  }

  /** Items stay under the fighter's joints so movement, squash and KO poses carry the full kit. */
  equip(handle, equipped) {
    const groups = [];
    for (const [slot, id] of Object.entries(equipped)) {
      if (!id) continue;
      const g = this.build(id, slot); groups.push(g);
      if (g.userData.signatureClothes) {
        const mount = g.userData.natural === 'body' ? 'mountBody' : g.userData.natural === 'head' ? 'mountHead' : { head: 'mountHead', body: 'mountBody', weapon: 'mountWeapon', trinket: 'mountTrinket' }[slot];
        handle.joints[mount].add(g);
      } else wear(handle, g, this.records[id]?.tier || 'common');
      if (this.arenaQuality) arenaTessellation(g);
      mergeItem(g);
    }
    return groups;
  }

  /** Restore the tier tint after LOOK3's temporary white hit flash ends. */
  restoreGlow(groups) {
    for (const g of groups) g.traverse((m) => {
      if (m.isMesh && m.material.userData.tierGlow) { m.material.emissive.copy(m.material.userData.tierGlow); m.material.emissiveIntensity = TIER_EMISSION; }
    });
  }

  clear(handle) {
    for (const name of MOUNTS) {
      const mount = handle.joints[name];
      for (const g of [...mount.children]) { mount.remove(g); this.dispose(g); }
    }
  }

  floor(id) {
    const item = this.build(id);
    if (this.arenaQuality) arenaTessellation(item);
    mergeItem(item);
    const g = onFloor(item, this.records[id]?.tier || 'common');
    if (this.arenaQuality) arenaTessellation(g);
    g.userData.itemRow = id; g.userData.item = item;
    g.userData.floating = g.children[g.children.length - 1];
    g.userData.restY = g.userData.floating.position.y; return g;
  }

  /** Free owned geometry and materials. Kit floor glow textures are shared and stay cached by kit3d. */
  dispose(group) {
    const geometries = new Set(), materials = new Set();
    group.traverse((o) => { if (o.isMesh) { geometries.add(o.geometry); (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => materials.add(m)); } });
    geometries.forEach((g) => g.dispose()); materials.forEach((m) => m.dispose());
  }
}
