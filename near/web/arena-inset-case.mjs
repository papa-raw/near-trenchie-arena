// F19: a click picks the nearest body inside the pick radius, and only that. Run: node near/web/arena-inset-case.mjs
import assert from 'node:assert/strict';
let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
import { pickFighter } from './arena/pick.mjs';
const at = { a: { x: 100, y: 100 }, b: { x: 130, y: 100 }, c: { x: 400, y: 300 } }, screenOf = (id) => at[id];
ok(pickFighter(['a', 'b', 'c'], screenOf, 105, 101) === 'a', 'a click near a picks a');
ok(pickFighter(['a', 'b', 'c'], screenOf, 125, 100) === 'b', 'a click nearer b picks b');
ok(pickFighter(['a', 'b', 'c'], screenOf, 400, 340) === 'c', 'a click within 46 px of c picks c');
ok(pickFighter(['a', 'b', 'c'], screenOf, 250, 200) === null, 'a click on empty sand picks nobody');
ok(pickFighter(['a'], (id) => null, 100, 100) === null, 'a body that is off screen cannot be picked');
ok(pickFighter([], screenOf, 100, 100) === null, 'nobody to pick');
console.log('arena-inset-case: ' + checks + ' checks passed');
