// One count-only prediction case: real feed, host ranking, sign markup and live banner projection.
// node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-points-off-case.mjs
import './arena-view-fix-env.mjs';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { slip } from './arena/feed.mjs';
import { boards, columnsHtml } from './arena/sign.mjs';
import { Hud } from './arena/hud.mjs';

const failures = [];
function check(name, fn) { try { fn(); console.log('PASS ' + name); } catch (e) { failures.push(name + ': ' + e.message); } }
const text = slip({ kind: 'res', who: 'pebble', level: 2, points: 557 }, (id) => id).parts.map((p) => p.text).join('');
check('feed says correct with no points', () => assert.equal(text, 'MADE 2+ KOs: correct'));

const rows = [];
for (const [persona, count, reward, house] of [['rare', 1, 2000, false], ['steady', 6, 1, false], ['coral', 6, 0, false], ['house-rare', 1, 2000, true], ['house-steady', 4, 1, true]]) {
  for (let i = 0; i < count; i++) rows.push({ kind: 'life', persona, house, result: 'correct', reward_points: reward, kos: 2, day: '2026-11-13', at_ns: '1' });
}
rows.push({ kind: 'life', persona: 'old', house: false, result: 'correct', reward_points: 9999, kos: 2, day: '2026-11-12', at_ns: '1' });
rows.push({ kind: 'life', persona: 'failure', house: false, result: 'failure', reward_points: 9999, kos: 0, day: '2026-11-13', at_ns: '1' });
const data = JSON.parse(execFileSync('python3', ['-B', '-c', 'import json,sys; from near.arena.predict import leaderboards; print(json.dumps(leaderboards(json.load(sys.stdin), "2026-11-13", top=2)))'], { input: JSON.stringify(rows), encoding: 'utf8' }));
check('host ranks count before top limit, ties by persona; day and house stay separate', () => {
  assert.deepEqual(data.boards.most_correct_day.players.map((r) => [r.persona, r.correct]), [['coral', 6], ['steady', 6]]);
  assert.deepEqual(data.boards.most_correct_day.house.map((r) => [r.persona, r.correct]), [['house-steady', 4], ['house-rare', 1]]);
  assert.deepEqual(data.most_correct.map((r) => r.persona), ['coral', 'steady']);
  assert.equal(data.boards.most_correct_day.house.find((r) => r.persona === 'house-rare').reward_points, 2000, 'numeric public fields retained');
});
const projected = boards(data, 'players', 3);
check('wall sign displays correct counts, including a zero-points correct life', () => {
  assert.deepEqual(projected.pr.rows.map((r) => [r.id, r.num]), [['coral', 6], ['steady', 6]]);
  const html = columnsHtml(projected, { side: 'players', name: (id) => id, face: () => null, dev: () => false }).pr;
  assert.doesNotMatch(html, /points|2000/);
  assert.match(html, /6.*✓/);
});
check('live Predictions banner orders and displays today correct counts', () => {
  assert.deepEqual(Hud.prototype.correctToday.call({ boards: data }), [{ id: 'coral', n: 6 }, { id: 'steady', n: 6 }, { id: 'house-steady', n: 4 }, { id: 'house-rare', n: 1 }]);
});
assert.deepEqual(failures, []);
console.log('points-off-case: feed, host top limits, wall sign and live banner use correct counts');
