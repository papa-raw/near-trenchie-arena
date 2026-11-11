// Name tags in a crowd: no two shown tags overlap; your fighter, its focus target and the speaker always
// show; a shown tag keeps its place while the crowd shuffles (no flicker).
//   node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-tags-crowd-case.mjs
import assert from 'node:assert/strict';
import { layoutTags, TIER } from './arena/tag-layout.mjs';
import { Social, SAY_EMOJI_MS } from './arena/social.mjs';

const overlap = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
let seed = 7;
const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);

const report = [];
for (const [W, H, tagH, ppt] of [[1440, 900, 16, 42], [390, 844, 15, 17]]) {
  for (const crowd of [1, 2, 3]) {
    // ten bodies inside a 3-tile cluster (the budget scene's crowd) plus six around the ring, tags 40-110 px wide
    const cx = W * (0.35 + 0.1 * crowd), cy = H * 0.5;
    const bodies = Array.from({ length: 16 }, (_, i) => {
      const near = i < 10, a = rnd() * Math.PI * 2, r = near ? rnd() * 1.5 * ppt : (4 + rnd() * 3) * ppt;
      return { id: 'f' + i, x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r * 0.6, w: 40 + Math.round(rnd() * 70), depth: rnd() };
    });
    const mustIds = ['f3', 'f7', 'f9'];   // your fighter, its focus target, the speaker: all inside the cluster
    let prev = new Map(), shownCounts = [], flips = 0;
    for (let frame = 0; frame < 120; frame++) {
      for (const b of bodies) { b.x += (rnd() - 0.5) * 1.2; b.y += (rnd() - 0.5) * 0.8; }   // a crowd shuffling at 60 Hz
      const items = bodies.map((b) => ({ id: b.id, ax: b.x, ay: b.y, w: b.w, h: tagH, depth: b.depth,
        tier: mustIds.includes(b.id) ? TIER.must : b.id === 'f0' ? TIER.notable : TIER.other }));
      const bars = bodies.map((b) => ({ x: b.x - 23, y: b.y + 6, w: 46, h: 8 }));   // each body's HP bar below its feet
      const out = layoutTags(items, { w: W, h: H, prev, obstacles: bars });
      const shown = [...out].filter(([, r]) => r.shown);
      for (let i = 0; i < shown.length; i++) for (let j = i + 1; j < shown.length; j++)
        assert.ok(!overlap(shown[i][1], shown[j][1]), `${W}px crowd ${crowd} frame ${frame}: ${shown[i][0]} overlaps ${shown[j][0]}`);
      for (const id of mustIds) assert.ok(out.get(id).shown, `${W}px crowd ${crowd}: ${id} (must win) is shown`);
      for (const [id, r] of shown) for (const bar of bars) assert.ok(!overlap(r, bar), `${W}px crowd ${crowd} frame ${frame}: ${id}'s tag covers an HP bar`);
      for (const [id, r] of out) {
        assert.ok(r.x >= 4 && r.x + r.w <= W - 4, `${id} stays on screen`);
        const b = bodies.find((q) => q.id === id);
        const rows = mustIds.includes(id) ? 7 : 4;   // a must-win may stack up to 6 rows when bars and tags fill its spot
        if (r.shown) assert.ok(Math.abs(r.x + r.w / 2 - b.x) <= 1.1 * r.w + 1 && b.y - (r.y + r.h) <= rows * (tagH + 1) + 2 && r.y <= b.y, `${id} stays by its fighter`);
        if (frame && prev.get(id).shown !== r.shown) flips++;
      }
      shownCounts.push(shown.length); prev = out;
    }
    assert.ok(flips <= 16, `${W}px crowd ${crowd}: tags hold steady while the crowd shuffles (${flips} show/hide flips in 120 frames)`);
    report.push({ width: W, crowd, shownMin: Math.min(...shownCounts), shownMax: Math.max(...shownCounts), flips });
  }
}

// three must-wins stacked on one spot still all show and never overlap each other
const pile = ['a', 'b', 'c'].map((id) => ({ id, ax: 200, ay: 300, w: 90, h: 16, depth: 0, tier: TIER.must }));
const out = layoutTags(pile.concat([{ id: 'd', ax: 200, ay: 300, w: 90, h: 16, depth: 9, tier: TIER.other }]), { w: 390, h: 844 });
const ms = ['a', 'b', 'c'].map((id) => out.get(id));
assert.ok(ms.every((r) => r.shown) && !overlap(ms[0], ms[1]) && !overlap(ms[0], ms[2]) && !overlap(ms[1], ms[2]), 'three must-wins on one spot');

// must-wins whose every nearby slot is walled off (HP bars across rows -3..+1) stack further up, never on each other
const wall = [{ x: 0, y: 300 - 4 * 17 - 2, w: 390, h: 5 * 17 + 4 }];
const stacked = layoutTags(['a', 'b'].map((id) => ({ id, ax: 200, ay: 300, w: 90, h: 16, depth: 0, tier: TIER.must })), { w: 390, h: 844, obstacles: wall });
const [sa, sb] = ['a', 'b'].map((id) => stacked.get(id));
assert.ok(sa.shown && sb.shown && !overlap(sa, sb), 'two walled-off must-wins stack');
assert.ok(!overlap(sa, wall[0]) && !overlap(sb, wall[0]), 'and keep clear of the bars when the column above is free');

// the speaker set: who spoke within the emoji's 3 s
const s = Object.create(Social.prototype); s.latest = new Map([['x', { at: 1000 }], ['y', { at: 1000 - SAY_EMOJI_MS - 1 }]]);
assert.deepEqual([...s.speaking(1000)], ['x']);
process.stdout.write(JSON.stringify({ ok: true, crowds: report }) + '\n');
