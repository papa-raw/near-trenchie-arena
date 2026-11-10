// W14 (JS half): decode of a recorded server tick, and the round trip back to the same bytes.
// Run: node near/web/arena-codec-case.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { decode, encode, SLOTS } from './arena/codec.mjs';

let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const text = fs.readFileSync(new URL('./arena/fixtures/tick-recorded.json', import.meta.url), 'utf8');
const s = decode(text);
ok(s.version === 1 && s.tick > 0, 'version and tick');
ok(s.fighters.length === 14 && s.names.length === 14, 'fourteen house fighters');
ok(s.fighters.every((f) => SLOTS.every((slot) => typeof f.items[slot] === 'string')), 'every fighter carries four slot items');
ok(s.fighters.every((f) => f.x >= -13000 && f.x <= 13000 && f.dir >= 0 && f.dir < 360), 'positions in milli-tiles, direction in degrees');
ok(s.fighters.every((f) => s.names[f.idx] === f.id), 'ids index the name table');
ok(s.fighters.every((f) => f.target === null || s.names.includes(f.target)), 'targets resolve to names');
ok(encode(s) === text, 'encode(decode(frame)) is the frame byte for byte');
// a decode of a re-encode is the same object (stable under repetition)
ok(JSON.stringify(decode(encode(s))) === JSON.stringify(s), 'decode(encode(x)) equals x');
// a wrong version is refused, never guessed
assert.throws(() => decode(JSON.stringify([2, 1, [], [], [], [], [], [], []])), /version/); checks++;
console.log('arena-codec-case: ' + checks + ' checks passed, frame ' + text.length + ' bytes, tick ' + s.tick);
