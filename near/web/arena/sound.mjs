// Sound (W19, Q15): synthesised hits and KO stings, and a looping island tune that starts after the viewer's first click,
// with a mute. Everything is made from oscillators and filtered noise at run time, so there is no audio file and no
// licence: the tune is original (a seeded pentatonic walk). The mapping from game events to sounds and the tune itself are
// pure functions, tested in arena-sound-case.mjs; only Sound (the last class) touches Web Audio.

export const BPM = 84, BEATS_PER_BAR = 4, BARS = 8;
const PENTA = [0, 2, 4, 7, 9];                      // C major pentatonic pitch classes: nothing in it can clash
export const midiToHz = (m) => 440 * Math.pow(2, (m - 69) / 12);

// splitmix32: the same walk every time the tune loops, on every machine
function mix32(seed) { let s = seed >>> 0; return () => { s = (s + 0x9E3779B9) >>> 0; let z = s; z = Math.imul(z ^ (z >>> 16), 0x85EBCA6B); z = Math.imul(z ^ (z >>> 13), 0xC2B2AE35); return ((z ^ (z >>> 16)) >>> 0) / 4294967296; }; }

// One bar of the tune: a lead walking the pentatonic scale around the middle of the keyboard and a bass note on beats 1 and 3.
// `bar` can be any integer: the tune is BARS long and loops.
export function tuneBar(bar) {
  const b = ((bar % BARS) + BARS) % BARS, r = mix32(7919 * (b + 1));
  const degrees = [0, 1, 2, 4, 3, 2, 1, 0];          // the shape of a phrase, repeated each 2 bars with a different seed
  const notes = []; let beat = 0, deg = degrees[b] ?? 0;
  while (beat < BEATS_PER_BAR) {
    const dur = [0.5, 1, 1, 1.5][Math.floor(r() * 4)], len = Math.min(dur, BEATS_PER_BAR - beat);
    if (r() > 0.18) { // a rest now and then, so it breathes
      deg = Math.max(0, Math.min(9, deg + [-1, 0, 1, 2, -2][Math.floor(r() * 5)]));
      const octave = 5 + Math.floor(deg / 5), pc = PENTA[deg % 5];
      notes.push({ kind: 'lead', beat, dur: len * 0.9, midi: 12 * octave + pc });
    }
    beat += len;
  }
  const root = [0, 0, 7, 7, 9, 9, 4, 7][b];           // C C G G A A E G: a slow, cheerful turn
  notes.push({ kind: 'bass', beat: 0, dur: 1.6, midi: 36 + root }, { kind: 'bass', beat: 2, dur: 1.6, midi: 36 + (root === 9 ? 4 : root) });
  return notes;
}

// Game event -> sound. `ev` is the sim's event dict (kind, damage, weapon, row ...). `tier` tells legendary grabs apart.
export function soundForEvent(ev, info = {}) {
  switch (ev.kind) {
    case 'hit': return { name: ev.damage >= 18 ? 'hit-heavy' : 'hit-light', gain: Math.min(1, 0.4 + (ev.damage || 0) / 40) };
    case 'ko': return { name: 'ko', gain: 1 };
    case 'grab': return ev.destroyed ? null : { name: info.tier === 'legendary' ? 'grab-legendary' : 'grab', gain: 0.8 };
    case 'attack': return { name: ev.weapon === 'swing' || ev.weapon === 'lunge' ? 'whoosh' : 'zip', gain: 0.35 };
    case 'signature': return { name: 'signature', gain: 0.7 };
    case 'respawn': return { name: 'pop', gain: 0.5 };
    default: return null;
  }
}
// at most one of a kind in `gapMs`, so a crowd of hits is a texture and not a wall
export const MIN_GAP_MS = { 'hit-light': 45, 'hit-heavy': 70, ko: 150, grab: 80, 'grab-legendary': 600, whoosh: 90, zip: 90, signature: 200, pop: 150 };
export function shouldPlay(name, nowMs, lastByName) {
  const last = lastByName.get(name) ?? -1e9;
  if (nowMs - last < (MIN_GAP_MS[name] ?? 50)) return false;
  lastByName.set(name, nowMs); return true;
}

// ---- Web Audio -------------------------------------------------------------------------------------------------------
export class Sound {
  constructor() {
    this.ctx = null; this.master = null; this.muted = false; this.started = false; this.last = new Map(); this.bar = 0; this.nextBarAt = 0; this.timer = null; this.voices = 0; this.noise = null;
    try { this.muted = localStorage.getItem('arena-muted') === '1'; } catch (e) { /* storage may be blocked: the mute just does not persist */ }
    const unlock = () => this.unlock();
    for (const t of ['pointerdown', 'keydown', 'touchstart']) addEventListener(t, unlock, { once: false, passive: true });
    this.onChange = null;
  }
  get state() { return !this.ctx ? 'waiting for a click' : this.muted ? 'muted' : 'on'; }

  unlock() { // browsers start audio only after a gesture: the first click, key or tap starts it
    if (this.started) { if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
    this.started = true; this.ctx = new AC();
    this.master = this.ctx.createGain(); this.master.gain.value = this.muted ? 0 : 0.5; this.master.connect(this.ctx.destination);
    const len = this.ctx.sampleRate; this.noise = this.ctx.createBuffer(1, len, this.ctx.sampleRate); const d = this.noise.getChannelData(0); const r = mix32(1); for (let i = 0; i < len; i++) d[i] = r() * 2 - 1;
    this.nextBarAt = this.ctx.currentTime + 0.2; this.timer = setInterval(() => this.schedule(), 120); this.schedule();
    if (this.onChange) this.onChange(this.state);
  }
  setMuted(m) {
    this.muted = m; try { localStorage.setItem('arena-muted', m ? '1' : '0'); } catch (e) { /* ignore */ }
    if (this.master) this.master.gain.setTargetAtTime(m ? 0 : 0.5, this.ctx.currentTime, 0.05);
    if (this.onChange) this.onChange(this.state);
  }
  toggle() { if (!this.started) this.unlock(); this.setMuted(!this.muted); return this.muted; }

  // the tune: schedule whole bars a little ahead of the clock
  schedule() {
    if (!this.ctx || this.ctx.state !== 'running') return;
    const spb = 60 / BPM;
    while (this.nextBarAt < this.ctx.currentTime + 0.6) {
      for (const n of tuneBar(this.bar)) this.tone(n.kind === 'bass' ? 'triangle' : 'sine', midiToHz(n.midi), this.nextBarAt + n.beat * spb, n.dur * spb, n.kind === 'bass' ? 0.16 : 0.11, 0.02);
      this.bar++; this.nextBarAt += BEATS_PER_BAR * spb;
    }
  }

  tone(type, hz, at, dur, gain, attack = 0.005, hz2 = null, pan = 0) {
    const c = this.ctx, o = c.createOscillator(), g = c.createGain();
    o.type = type; o.frequency.setValueAtTime(hz, at); if (hz2) o.frequency.exponentialRampToValueAtTime(hz2, at + dur);
    g.gain.setValueAtTime(0.0001, at); g.gain.exponentialRampToValueAtTime(Math.max(0.0002, gain), at + attack); g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    let out = g; if (pan && c.createStereoPanner) { const p = c.createStereoPanner(); p.pan.value = pan; g.connect(p); out = p; }
    o.connect(g); out.connect(this.master); o.start(at); o.stop(at + dur + 0.05);
  }
  burst(at, dur, gain, f0, f1, type = 'bandpass', pan = 0) {
    const c = this.ctx, s = c.createBufferSource(), f = c.createBiquadFilter(), g = c.createGain();
    s.buffer = this.noise; f.type = type; f.frequency.setValueAtTime(f0, at); f.frequency.exponentialRampToValueAtTime(f1, at + dur); f.Q.value = 1.2;
    g.gain.setValueAtTime(gain, at); g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    let out = g; if (pan && c.createStereoPanner) { const p = c.createStereoPanner(); p.pan.value = pan; g.connect(p); out = p; }
    s.connect(f); f.connect(g); out.connect(this.master); s.start(at, Math.random() * 0.5); s.stop(at + dur + 0.05);
  }

  // play a named sound; `pan` -1..1 follows the screen position of the event
  play(sound, nowMs, pan = 0) {
    if (!sound || !this.ctx || this.ctx.state !== 'running' || this.muted) return;
    if (!shouldPlay(sound.name, nowMs, this.last) || this.voices > 14) return;
    const c = this.ctx, t = c.currentTime + 0.005, g = sound.gain; this.voices++; setTimeout(() => { this.voices--; }, 300);
    switch (sound.name) {
      case 'hit-light': this.burst(t, 0.07, 0.35 * g, 2400, 900, 'bandpass', pan); this.tone('sine', 240, t, 0.08, 0.3 * g, 0.002, 120, pan); break;
      case 'hit-heavy': this.burst(t, 0.12, 0.5 * g, 1600, 300, 'lowpass', pan); this.tone('sine', 150, t, 0.18, 0.55 * g, 0.002, 55, pan); this.tone('square', 320, t, 0.06, 0.12 * g, 0.002, 160, pan); break;
      case 'ko': [76, 72, 67, 60].forEach((m, i) => this.tone('triangle', midiToHz(m), t + i * 0.09, 0.22, 0.28, 0.005, null, pan)); this.tone('sine', 120, t, 0.35, 0.55, 0.003, 40, pan); break;
      case 'grab': this.tone('sine', midiToHz(76), t, 0.1, 0.22, 0.004, null, pan); this.tone('sine', midiToHz(83), t + 0.07, 0.14, 0.22, 0.004, null, pan); break;
      case 'grab-legendary': [72, 76, 79, 84, 88].forEach((m, i) => this.tone('triangle', midiToHz(m), t + i * 0.07, 0.4, 0.2, 0.005, null, pan)); break;
      case 'whoosh': this.burst(t, 0.14, 0.18 * g, 500, 2400, 'bandpass', pan); break;
      case 'zip': this.tone('sine', 900, t, 0.09, 0.12 * g, 0.003, 1500, pan); break;
      case 'signature': this.tone('sawtooth', 180, t, 0.4, 0.14, 0.01, 760, pan); this.burst(t, 0.4, 0.14, 300, 3000, 'bandpass', pan); break;
      case 'pop': this.tone('sine', 300, t, 0.1, 0.25, 0.003, 700, pan); break;
      default: break;
    }
  }
}
