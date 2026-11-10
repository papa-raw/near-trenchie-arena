// W19: the tune loops and stays in key, every game event maps to a sound, and a crowd of hits is rate limited.
// Run: node near/web/arena-sound-case.mjs  (the Web Audio part is not run here: it needs a browser and a click)
import assert from 'node:assert/strict';
import { tuneBar, soundForEvent, shouldPlay, midiToHz, BARS, BEATS_PER_BAR, MIN_GAP_MS } from './arena/sound.mjs';

let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const PENTA = new Set([0, 2, 4, 7, 9]);

// the tune: 8 bars, loops, deterministic, in C pentatonic, inside the beat grid
for (let bar = 0; bar < BARS; bar++) {
  const notes = tuneBar(bar);
  ok(JSON.stringify(notes) === JSON.stringify(tuneBar(bar + BARS)) && JSON.stringify(notes) === JSON.stringify(tuneBar(bar - BARS)), 'bar ' + bar + ' loops');
  ok(notes.some((n) => n.kind === 'bass') && notes.some((n) => n.kind === 'lead'), 'bar ' + bar + ' has a bass and a lead');
  for (const n of notes) {
    ok(PENTA.has(n.midi % 12), 'bar ' + bar + ' note ' + n.midi + ' is in the pentatonic scale');
    ok(n.beat >= 0 && n.beat < BEATS_PER_BAR && n.dur > 0, 'note starts inside the bar');
    if (n.kind === 'lead') ok(n.midi >= 60 && n.midi <= 84, 'lead in range');
    if (n.kind === 'bass') ok(n.midi >= 36 && n.midi <= 48, 'bass in range');
  }
}
ok(new Set(Array.from({ length: BARS }, (_, b) => JSON.stringify(tuneBar(b)))).size === BARS, 'the eight bars differ');
ok(Math.abs(midiToHz(69) - 440) < 1e-9 && Math.abs(midiToHz(81) - 880) < 1e-9, 'A4 is 440 Hz');

// events -> sounds
ok(soundForEvent({ kind: 'hit', damage: 7 }).name === 'hit-light', 'a light hit');
ok(soundForEvent({ kind: 'hit', damage: 30 }).name === 'hit-heavy', 'a heavy hit');
ok(soundForEvent({ kind: 'hit', damage: 30 }).gain > soundForEvent({ kind: 'hit', damage: 7 }).gain, 'heavier is louder');
ok(soundForEvent({ kind: 'ko' }).name === 'ko', 'a KO sting');
ok(soundForEvent({ kind: 'grab' }, { tier: 'legendary' }).name === 'grab-legendary' && soundForEvent({ kind: 'grab' }, { tier: 'common' }).name === 'grab', 'a legendary grab sparkles');
ok(soundForEvent({ kind: 'grab', destroyed: true }) === null, 'a destroyed duplicate is silent');
ok(soundForEvent({ kind: 'attack', weapon: 'swing' }).name === 'whoosh' && soundForEvent({ kind: 'attack', weapon: 'shot' }).name === 'zip', 'attacks');
ok(soundForEvent({ kind: 'signature' }).name === 'signature' && soundForEvent({ kind: 'respawn' }).name === 'pop', 'signature and respawn');
ok(soundForEvent({ kind: 'floor_loss' }) === null && soundForEvent({ kind: 'intent_refused' }) === null, 'unrelated events are silent');

// a crowd: 14 light hits in 100 ms play at most 3
const last = new Map(); let played = 0;
for (let i = 0; i < 14; i++) if (shouldPlay('hit-light', 1000 + i * 7, last)) played++;
ok(played >= 1 && played <= 3, 'a burst of 14 hits plays ' + played + ' sounds');
ok(shouldPlay('hit-light', 1000 + 7 * 14 + MIN_GAP_MS['hit-light'], last), 'and plays again after the gap');
ok(shouldPlay('ko', 1000, last) && !shouldPlay('ko', 1100, last), 'a KO sting is not stacked within 150 ms');
console.log('arena-sound-case: ' + checks + ' checks passed');
