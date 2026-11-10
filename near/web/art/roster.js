/* roster.js — the 14 house rows and every item record, read from kits.js (generated from the lore kits).
 * ITEMS: map by id; ROSTER: the 14 house rows (trenchieId, name, tag, paletteIds, kit, signaturePiece, legendary).
 */
import { KITS } from './kits.js';
import { LOOK3 } from './look3.js';

export const ITEMS = {};
for (const it of KITS.items) ITEMS[it.id] = Object.freeze(Object.assign({}, it, { stats: Object.freeze(Object.assign({}, it.stats)) }));
Object.freeze(ITEMS);
export const ROSTER = KITS.roster;
export const RIVALS = KITS.rivals || [];
export const ALLIANCES = KITS.alliances || [];
LOOK3.setItemRecords(ITEMS);
