// Board 1's Follow button: window.ArenaView.follow(id) follows your own trenchie from the page's panel, now or once it is
// back in the ring; unfollow() closes it; a click on the ring drops a pending follow. Run: node near/web/arena-follow-hook-case.mjs
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const { arenaView } = await import('./arena/follow.mjs');

// the real Inset's follow/clear semantics (a second follow of the same id toggles it off), without three.js
const inset = { followId: null, follow(id) { this.followId = id === this.followId ? null : id; }, clear() { this.followId = null; } };
const hud = { followed: null };
let pos = new Map([['dev-bertie', { state: 'bench' }], ['leeth', { state: 'alive' }]]);
const timers = []; const heard = [];
const view = arenaView({ inset, hud, positions: () => pos, setTimer: (f) => { timers.push(f); return timers.length; }, clearTimer: (n) => { timers[n - 1] = null; }, announce: (id) => heard.push(id) });
const tick = () => timers.forEach((f) => f && f());

ok(view.follow('leeth') === true && view.followed() === 'leeth' && hud.followed === 'leeth', 'a fighter in the ring is followed at once');
ok(view.follow('leeth') === true && view.followed() === 'leeth', 'following the same fighter again never toggles it off');
ok(view.follow('dev-bertie') === false && view.waitingFor() === 'dev-bertie' && view.followed() === 'leeth', 'a benched fighter is waited for; the view stays where it was');
tick(); ok(view.followed() === 'leeth', 'still on the bench: nothing changes');
pos = new Map([['dev-bertie', { state: 'alive' }], ['leeth', { state: 'alive' }]]); tick();
ok(view.followed() === 'dev-bertie' && hud.followed === 'dev-bertie' && view.waitingFor() === null, 'back in the ring: followed, and the wait ends');
view.unfollow(); ok(view.followed() === null && hud.followed === null, 'unfollow closes the view');
pos.set('dev-bertie', { state: 'bench' }); view.follow('dev-bertie');
view.clicked(); pos.set('dev-bertie', { state: 'alive' }); tick();
ok(view.followed() === null, 'a click on the ring drops a pending follow');
ok(view.follow('') === false && view.follow(null) === false, 'no id, no follow');
ok(heard.includes('dev-bertie') && heard.includes(null), 'each change is announced');

// main.mjs wires it: window.ArenaView is set, ?follow= uses it, and the ring click and the close mark report to it
const main = await readFile(new URL('./arena/main.mjs', import.meta.url), 'utf8');
ok(/window\.ArenaView\s*=\s*arenaView\(/.test(main), 'main.mjs exposes window.ArenaView');
ok(/ArenaView\.follow\(followWant\)/.test(main), '?follow= goes through the same hook');
ok(/followView\.clicked\(\)/.test(main), 'a click on the ring reports to the hook');
const { spawnSync } = await import('node:child_process');
const parsed = spawnSync(process.execPath, ['--check', new URL('./arena/main.mjs', import.meta.url).pathname], { encoding: 'utf8' });
ok(parsed.status === 0, 'main.mjs parses: ' + parsed.stderr.split('\n').filter(Boolean).slice(-1)[0]);
console.log('arena-follow-hook-case: ' + checks + ' checks passed');
