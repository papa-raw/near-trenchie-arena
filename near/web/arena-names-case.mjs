// Names and the DEV label. Run: node near/web/arena-names-case.mjs
import assert from 'node:assert/strict';
import { isDev, shortName, tagText } from './arena/names.mjs';
let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const roster = [{ trenchieId: 'captain-banana-zone', tag: 'Banana Zone' }, { trenchieId: 'satrenchi', name: 'Satrenchi' }];
ok(isDev('dev-patwatch') && isDev('dev-claude'), 'dev- ids are DEV');
ok(!isDev('captain-banana-zone') && !isDev('patwatch') && !isDev('dev-') && !isDev('device-1') && !isDev(null) && !isDev(undefined), 'nothing else is');
ok(shortName(roster, 'captain-banana-zone') === 'Banana Zone' && shortName(roster, 'satrenchi') === 'Satrenchi', 'house names come from the roster');
ok(shortName(roster, 'dev-patwatch') === 'patwatch', 'a DEV tag drops the prefix');
ok(shortName(roster, 'dev-averyveryverylongname') === 'averyveryve…', 'and is clipped to 12');
ok(shortName(roster, 'someone-else') === 'someone-else', 'a stranger keeps its id');
ok(tagText(roster, 'dev-patwatch') === 'patwatch DEV', 'the panel art gets the word');
ok(tagText(roster, 'satrenchi') === 'Satrenchi', 'a house name does not');
ok(!/DEV/.test(tagText(roster, 'captain-banana-zone')), 'no house trenchie ever reads DEV');
console.log('arena-names-case: ' + checks + ' checks passed');
