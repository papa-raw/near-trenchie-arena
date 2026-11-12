// The corner buttons beside the open trenchie panel on a phone (a review found that at 390 with the panel open,
// Sound and How it works sat on the plank over the Predictions board). Agreed with board 1: at <= 600 px the sheet never
// rises above y 290; the buttons turn compact (two 40 px round buttons) and sit just above the sheet's top edge,
// right-aligned, under the plank; if a sheet ever rises far enough that they would reach the plank, they hide.
//   node near/web/arena-btn-panel-case.mjs
import assert from 'node:assert/strict';
import { hudLayout, cornerHidden, COMPACT } from './arena/hud-layout.mjs';

let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };
const hit = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
const worded = { w: 250, h: 44 };   // the two worded buttons at 390
const box = (L, view) => ({ x: view.w - L.right - L.corner.w, y: view.h - L.bottom - L.corner.h, w: L.corner.w, h: L.corner.h });
const PHONE = { w: 390, h: 844 }, PLANK = { x: 8, y: 0, w: 374, h: 149 };   // measured live at 390

// 1. 390, fight and bench: the sheet's top at y 290 (board 1's contract): compact, above the sheet, under the plank
for (const state of ['fight', 'bench']) {
  const sheet = { x: 0, y: 290, w: 390, h: 554 }, L = hudLayout(PHONE, { open: sheet, closed: [] }, worded), b = box(L, PHONE);
  ok(L.compact && L.corner.w === COMPACT.w && L.corner.h === 40, state + ': compact, two 40 px round buttons');
  ok(b.y + b.h <= sheet.y - 4 && b.y + b.h >= sheet.y - 10, state + ': just above the sheet (' + b.y + '..' + (b.y + b.h) + ')');
  ok(b.x + b.w === PHONE.w - 8 && b.x >= 0, state + ': right-aligned on screen (' + b.x + '..' + (b.x + b.w) + ')');
  ok(!hit(b, PLANK) && b.y >= PLANK.y + PLANK.h + 6, state + ': clear of the plank and its boards');
  ok(!hit(b, sheet), state + ': clear of the sheet');
  ok(!cornerHidden(L, PHONE, PLANK), state + ': shown');
  ok(L.feedHidden, state + ': the feed still hides while the sheet is up');
}

// 2. a sheet risen past its contract (the old bench, top y 120): the buttons would reach the plank, so they hide
{
  const L = hudLayout(PHONE, { open: { x: 0, y: 120, w: 390, h: 724 }, closed: [] }, worded), b = box(L, PHONE);
  ok(hit(b, PLANK), 'risen sheet: just above it would be on the plank (' + b.y + '..' + (b.y + b.h) + ')');
  ok(cornerHidden(L, PHONE, PLANK), 'risen sheet: hidden, never on a board');
}

// 3. no panel at 390: the worded buttons at the bottom, as approved
{
  const L = hudLayout(PHONE, { open: null, closed: [] }, worded);
  ok(!L.compact && L.corner === worded && L.bottom === 12, 'no panel: worded, at the bottom');
  ok(!cornerHidden(L, PHONE, PLANK), 'no panel: shown');
}

// 4. 1440 with the panel open: unchanged (worded, left of the panel)
{
  const L = hudLayout({ w: 1440, h: 900 }, { open: { x: 968, y: 12, w: 460, h: 876 }, closed: [] }, worded);
  ok(!L.compact && L.right === 1440 - 968 + 16 && L.free === 952, 'desktop: worded, left of the panel');
  ok(!cornerHidden(L, { w: 1440, h: 900 }, { x: 250, y: 0, w: 700, h: 150 }), 'desktop: shown');
}

console.log('arena-btn-panel-case: ' + checks + ' checks OK');
