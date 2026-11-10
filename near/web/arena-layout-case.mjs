// The banner clears every card at 1440 and 390, with and without a Players card. Run: node near/web/arena-layout-case.mjs
import assert from 'node:assert/strict';
import { placeBanner } from './arena/layout.mjs';
let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const overlap = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
const clear = (p, N, cards) => !cards.some((c) => overlap({ x: p.x, y: p.y, w: N.w, h: N.h }, c));

// 1440: the five-tag House card is 533 wide; the banner's natural place (465, 31) lies across its right end
const house = { x: 14, y: 12, w: 533, h: 76 }, houseLabel = { x: 22, y: 85, w: 40, h: 16 };
const players = { x: 14, y: 110, w: 170, h: 76 }, playersLabel = { x: 22, y: 183, w: 150, h: 16 };
let N = { x: 465, y: 31.5, w: 510, h: 101 };
let p = placeBanner(N, [house, houseLabel], 1440); ok(p.how === 'right' && p.x >= 555 && clear(p, N, [house, houseLabel]), 'house only, 1440: moves right of the card (' + p.x + ')');
p = placeBanner(N, [house, houseLabel, players, playersLabel], 1440); ok(p.how === 'right' && clear(p, N, [house, houseLabel, players, playersLabel]), 'with players, 1440: right of the cards, touching none');
// natural place already clear: it stays
N = { x: 700, y: 31.5, w: 500, h: 101 }; p = placeBanner(N, [house, houseLabel, players, playersLabel], 1440); ok(p.how === 'natural' && p.x === 700, 'far enough right: it stays');
// 1100 wide
N = { x: 455, y: 31.5, w: 528, h: 101 }; p = placeBanner(N, [house, houseLabel], 1100); ok(p.how === 'right' && p.x + N.w <= 1100 - 12, '1100: moves right and fits');
// 390: cards are small and stacked on the left; the banner is as wide as the screen: it goes below all of them
const h3 = { x: 6, y: 4, w: 218, h: 52 }, h3l = { x: 14, y: 58, w: 40, h: 16 }, p3 = { x: 6, y: 78, w: 86, h: 52 }, p3l = { x: 14, y: 132, w: 150, h: 16 };
N = { x: 33, y: 24, w: 324, h: 76 };
p = placeBanner(N, [h3, h3l], 390); ok(p.how === 'below' && clear(p, N, [h3, h3l]), '390, house only: below the card');
p = placeBanner(N, [h3, h3l, p3, p3l], 390); ok(p.how === 'below' && clear(p, N, [h3, h3l, p3, p3l]) && p.y >= 148, '390, with players: below BOTH cards and labels (y ' + p.y + ')');
ok(p.x >= 12 && p.x + N.w <= 390 - 12, 'and inside the screen');
// no banner, no answer
ok(placeBanner(null, [house], 1440) === null, 'no banner');
console.log('arena-layout-case: ' + checks + ' checks passed');
