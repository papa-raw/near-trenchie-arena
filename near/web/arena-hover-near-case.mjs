import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { placeQuirkPanel } from './arena/hover.mjs';
import { ROSTER } from './art/roster.js';
const distance = (a, b) => Math.hypot(a.x + a.w / 2 - b.x - b.w / 2, a.y + a.h / 2 - b.y - b.h / 2);
const overlap = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
let maximum = 0;
for (const width of [1780,390]) {
  const tags = ROSTER.map((row, i) => ({ id: row.trenchieId, x: width === 390 ? 64 + i % 2 * 116 : 700 + i % 4 * 88,
    y: 220 + Math.floor(i / (width === 390 ? 2 : 4)) * 23, w: 80, h: 17 }));
  // A broad nearby corner card makes the old overlap-first edge scan pick a far shore position.
  const cards = width === 1780 ? [{ x: 0, y: 0, w: 1200, h: 210 }] : [{ x: 0, y: 0, w: 200, h: 160 }];
  for (const anchor of tags) {
    const panel = placeQuirkPanel(anchor, { w: 230, h: 78 }, tags, width, 844, cards);
    const gap = distance(anchor, panel); maximum = Math.max(maximum, gap);
    assert.ok(gap <= 240, anchor.id + ' stays within 240 CSS px at ' + width + ', got ' + gap.toFixed(1));
    assert.ok(!tags.some((tag) => overlap(panel, tag)), anchor.id + ' body clears all tags');
    assert.ok(panel.x >= 8 && panel.x + panel.w <= width - 8);
  }
}
process.stdout.write(JSON.stringify({ ok: true, tags: 14, widths: [1780,390], maximumCenterDistance: +maximum.toFixed(1), bound: 240, tagOverlap: 0 }) + '\n');
