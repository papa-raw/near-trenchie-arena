// Board 3's weapon sizes and the /2 limits (Pat's item 57): every weapon made today (no "limits" field, so
// trenchie-item-limits/1) is drawn 2.5x on its mount and on the floor; a weapon made under trenchie-item-limits/2 is already
// authored at its full size, so it is drawn at limits-2.json's weapon_render_scale, 1x. No /2 item exists yet: the rule is
// in place before the first one. Run: node near/web/arena-weapon-scale-case.mjs
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const { weaponRenderScale, WEAPON_SCALE, LIMITS_2, LIMITS_2_RENDER_SCALE } = await import('./arena/weapon-scale.mjs');
const items = new URL('../items/', import.meta.url);

const limits2 = JSON.parse(await readFile(new URL('limits-2.json', items), 'utf8'));
ok(limits2.spec === LIMITS_2, 'the /2 name is limits-2.json\'s own');
ok(limits2.weapon_render_scale === LIMITS_2_RENDER_SCALE, 'a /2 weapon draws at limits-2.json\'s weapon_render_scale (' + limits2.weapon_render_scale + ')');
ok(WEAPON_SCALE === 2.5, 'a /1 weapon draws at the picked 2.5x');

// every weapon spec today is /1: drawn 2.5x, its rare row too (it draws the common spec)
const specs = {};
for (const f of await readdir(new URL('specs/', items))) if (f.endsWith('.json')) { const s = JSON.parse(await readFile(new URL('specs/' + f, items), 'utf8')); specs[s.id || f.replace(/\.json$/, '')] = s; }
const weapons = Object.entries(specs).filter(([, s]) => s.slot === 'weapon');
ok(weapons.length >= 7, 'the weapon specs are read (' + weapons.length + ')');
for (const [id, s] of weapons) {
  ok(!s.limits, id + ' has no limits field today (it is /1)');
  ok(weaponRenderScale(id, specs) === 2.5, id + ' draws at 2.5x');
  ok(weaponRenderScale(id.replace(/^c-/, 'r-'), specs) === 2.5, id.replace(/^c-/, 'r-') + ' (its rare row) draws at 2.5x');
}
// the first /2 weapon, by spec or by catalog row: 1x; an unknown or missing id keeps 2.5x
const made2 = { ...specs['c-swing'], id: 'cm-oar', limits: LIMITS_2 };
ok(weaponRenderScale('cm-oar', { ...specs, 'cm-oar': made2 }) === 1, 'a /2 weapon spec draws at 1x');
ok(weaponRenderScale('cm-oar', specs, { 'cm-oar': { slot: 'weapon', limits: LIMITS_2 } }) === 1, 'a /2 catalog row draws at 1x');
ok(weaponRenderScale('cm-unknown', specs) === 2.5 && weaponRenderScale(null, specs) === 2.5, 'an unknown or missing weapon keeps 2.5x');
ok(weaponRenderScale('cm-oar', { 'cm-oar': { ...made2, limits: 'trenchie-item-limits/1' } }) === 2.5, 'an explicit /1 keeps 2.5x');

// the arena uses the rule for the held weapon and for a dropped one
const actors = await readFile(new URL('./arena/actors.mjs', import.meta.url), 'utf8'), main = await readFile(new URL('./arena/main.mjs', import.meta.url), 'utf8');
ok(/mountWeapon\.scale\.setScalar\(weaponRenderScale\(this\.itemRenderer, /.test(actors), 'the held weapon\'s mount takes the rule');
ok(/fx\.floorWeaponScale = .*weaponRenderScale\(itemRenderer, id\)/.test(main), 'a dropped weapon on the floor takes the rule');
console.log('arena-weapon-scale-case: ' + checks + ' checks passed');
