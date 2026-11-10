// W6: KOs per hour played, 60-minute minimum, house in its own column, top 5. Run: node near/web/arena-leaderboard-case.mjs
import assert from 'node:assert/strict';
import { Leaderboard, HOUR_MS } from './arena/leaderboard.mjs';

let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const MIN = 60000;
const house = new Set(['sailor', 'eddie', 'moonwood', 'leeth', 'avichad', 'warrior', 'trenchtoly']);
// play `ids` for `ms` of page time, in 1 s steps starting at `from`
const play = (lb, ids, from, ms) => { for (let t = from; t <= from + ms; t += 1000) lb.presence(ids, t); };

// 1. the 60-minute minimum: 3 KOs in 20 minutes ranks as 3 per hour, not 9
let lb = new Leaderboard({ windowMs: 3 * HOUR_MS, isHouse: (id) => house.has(id) });
play(lb, ['lucky', 'steady'], 0, 20 * MIN);
for (let i = 0; i < 3; i++) lb.onKo('lucky', (i + 1) * 5 * MIN);
ok(Math.abs(lb.rate('lucky', 20 * MIN) - 3) < 1e-9, 'a 20-minute trenchie is ranked as if it played an hour: ' + lb.rate('lucky', 20 * MIN));

// 2. past an hour the rate is KOs over hours played: 6 KOs over 3 hours is 2 per hour
lb = new Leaderboard({ windowMs: 3 * HOUR_MS, isHouse: (id) => house.has(id) });
play(lb, ['grinder', 'lucky'], 0, 3 * HOUR_MS);
for (let i = 0; i < 6; i++) lb.onKo('grinder', (i + 1) * 25 * MIN);
for (let i = 0; i < 5; i++) lb.onKo('lucky', (i + 1) * 30 * MIN);
const now = 3 * HOUR_MS;
ok(Math.abs(lb.rate('grinder', now) - 2) < 0.02, 'six KOs over three hours is 2 an hour: ' + lb.rate('grinder', now));
ok(lb.rows(now)[0].id === 'grinder', 'the grinder leads the lucky one (2 an hour against 1.67)');

// 3. this hour: the window drops KOs older than an hour, and played time with them
lb = new Leaderboard({ isHouse: (id) => house.has(id) });
play(lb, ['a'], 0, 2 * HOUR_MS);
lb.onKo('a', 10 * MIN); lb.onKo('a', 70 * MIN); lb.onKo('a', 100 * MIN);
ok(lb.koCount('a', 2 * HOUR_MS) === 2 && lb.koCount('a', 70 * MIN + 1) === 1 && lb.koCount('a', 2 * HOUR_MS + 11 * MIN) === 1, 'at two hours the KOs from minutes 70 and 100 are inside the hour, the one from minute 10 is not; eleven minutes on, minute 70 has gone too');
ok(lb.playedMs('a', 2 * HOUR_MS) <= HOUR_MS + 1000, 'played time is clipped to the window');

// 4. columns: house in its own column; top 5 each; ties break by KOs then id; the single ranking is top 5 overall
lb = new Leaderboard({ isHouse: (id) => house.has(id) });
const ids = ['sailor', 'eddie', 'moonwood', 'leeth', 'avichad', 'warrior', 'trenchtoly', 'p1', 'p2', 'p3'];
play(lb, ids, 0, 10 * MIN);
ids.forEach((id, i) => { for (let k = 0; k < i % 5; k++) lb.onKo(id, 5 * MIN + k); });
const cols = lb.columns(10 * MIN);
ok(cols.house.length === 5 && cols.house.every((r) => r.house), 'five house rows, all house');
ok(cols.players.length === 3 && cols.players.every((r) => !r.house), 'the players column holds only players');
ok(cols.all.length === 5, 'the on-screen card shows five');
ok(cols.house.every((r, i) => i === 0 || cols.house[i - 1].perHour >= r.perHour), 'ranked by rate');
ok(JSON.stringify(lb.columns(10 * MIN)) === JSON.stringify(lb.columns(10 * MIN)), 'deterministic');

// 5. a trenchie that leaves for longer than the gap and returns keeps its earlier time but does not gain the gap
lb = new Leaderboard({ windowMs: 3 * HOUR_MS });
play(lb, ['x'], 0, 30 * MIN); play(lb, ['x'], 90 * MIN, 30 * MIN);
ok(Math.abs(lb.playedMs('x', 2 * HOUR_MS) - 60 * MIN) < 2000, 'time away is not counted as played: ' + (lb.playedMs('x', 2 * HOUR_MS) / MIN).toFixed(1) + ' min');
// 6. ties: the same rate and KOs, the one knocked out less often ranks higher; then the id
lb = new Leaderboard({ isHouse: () => true });
play(lb, ['a', 'b', 'c'], 0, 10 * MIN);
lb.onKo('a', MIN, 'z'); lb.onKo('b', 2 * MIN, 'z'); lb.onKo('c', 3 * MIN, 'z');
lb.onKo('z', 4 * MIN, 'a'); lb.onKo('z', 5 * MIN, 'a'); lb.onKo('z', 6 * MIN, 'b');
const order = lb.rows(10 * MIN).filter((r) => r.kos === 1).map((r) => r.id).join('');
ok(order === 'cba', 'equal KOs: c (never knocked out), then b (once), then a (twice): ' + order);
console.log('arena-leaderboard-case: ' + checks + ' checks passed');
