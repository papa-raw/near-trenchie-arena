// How big a held or dropped weapon is drawn (board 3, Pat's item 57; WEAPON-LIMITS.md). A weapon made under
// trenchie-item-limits/1 (every item without a "limits" field, so every item today) is drawn 2.5x on its mount, so a swing
// stick reaches about the swing's own hit range. One made under trenchie-item-limits/2 is already authored at its full size in
// /2's wider weapon box, so it is drawn at limits-2.json's weapon_render_scale, 1. Pure: no three.js, so node tests it.
export const WEAPON_SCALE = 2.5;
export const LIMITS_2 = 'trenchie-item-limits/2';
export const LIMITS_2_RENDER_SCALE = 1;   // limits-2.json "weapon_render_scale"; the case checks they agree

// specs: item id -> ItemSpec (a rare row 'r-x' draws the common 'c-x' spec); records: item id -> catalog row
export function weaponRenderScale(id, specs = {}, records = {}) {
  if (!id) return WEAPON_SCALE;
  const spec = specs[id] || specs[String(id).replace(/^r-/, 'c-')] || records[id];
  return spec && spec.limits === LIMITS_2 ? LIMITS_2_RENDER_SCALE : WEAPON_SCALE;
}
