import assert from 'node:assert/strict';
let place;
try { ({ placeQuirkPanel: place } = await import('./arena/hover.mjs')); }
catch (error) { if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error; place = (anchor, size) => ({ x: anchor.x, y: anchor.y, ...size }); }
const overlap = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
for (const width of [390, 1440]) {
  const anchor = { x: width / 2 - 50, y: 210, w: 100, h: 20 }, size = { w: 230, h: 68 };
  const neighbours = [anchor, { x: anchor.x - 30, y: 237, w: 140, h: 20 }, { x: anchor.x + 40, y: 180, w: 110, h: 20 }];
  const panel = place(anchor, size, neighbours, width, 844);
  assert.ok(!neighbours.some((rect) => overlap(panel, rect)), 'wrapped body clears adjacent tags at ' + width);
  assert.ok(panel.x >= 8 && panel.x + panel.w <= width - 8 && panel.y >= 8 && panel.y + panel.h <= 836);
}
process.stdout.write(JSON.stringify({ ok: true, widths: [390,1440], overlap: 0 }) + '\n');
