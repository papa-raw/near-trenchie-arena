import assert from 'node:assert/strict';
import * as layout from './arena/layout.mjs';
const feed = { x: 10, y: 746, w: 290, h: 88 }, natural = { x: 120, y: 808, w: 150, h: 26 };
const placed = layout.placeReplayStatus ? layout.placeReplayStatus(natural, feed, 390, 844) : natural;
const overlap = placed.x < feed.x + feed.w && placed.x + placed.w > feed.x && placed.y < feed.y + feed.h && placed.y + placed.h > feed.y;
assert.equal(overlap, false, 'replay-only status clears the feed at 390');
assert.ok(placed.y >= 8 && placed.y + placed.h <= 836);
process.stdout.write(JSON.stringify({ ok: true, width:390, status:placed, feedOverlap:0 }) + '\n');
