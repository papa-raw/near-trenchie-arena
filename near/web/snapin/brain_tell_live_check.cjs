// Live check of the owner's goal box prompt (brain.js tellAsk) on the real model, no browser: a forward persona and
// a calm one are each told "fight everyone"; prints each in-character reply and the behaviour each wrote.
// Run: NEARAI_API_KEY=... NODE_USE_ENV_PROXY=1 node near/web/snapin/brain_tell_live_check.cjs
'use strict';
const B = require('./brain.js');
const key = process.env.NEARAI_API_KEY;
if (!key) { console.error('needs NEARAI_API_KEY'); process.exit(2); }
const PERSONAS = {
  forward: { game: { name: 'Boom Crab', temperament: 'Restless', voice: ['LET’S GO, WHO’S NEXT?!'], tics: ['Shouts every plan out loud.'] },
             identity: { brief: 'A loud, forward newcomer who swings first and asks never.' } },
  calm: { game: { name: 'Still Pond', temperament: 'Serene', voice: ['Breathe first.'], tics: ['Counts to three before every swing.'] },
          identity: { brief: 'A calm newcomer, slow to anger, who would rather sit by the tide pool.' } }
};
const RING = { me: { hp: 100, x: 0, y: 0 }, near: [{ id: 'satrenchi', name: 'satrenchi', house: true, hp: 80, dx: 3, dy: 0 }], loot_on_floor: 0 };
(async () => {
  const out = {};
  for (const [kind, sheet] of Object.entries(PERSONAS)) {
    const rows = [];
    for (let i = 0; i < 3; i++) {
      const r = await B.chat('nearai', key, B.prefix(sheet, sheet.game.name), B.tellAsk('fight everyone', 'fight everyone', RING, null), { fetch: globalThis.fetch, maxTokens: 500 });
      if (!r.ok) { rows.push({ error: r.kind }); continue; }
      let p = null; try { p = JSON.parse(r.text.slice(r.text.indexOf('{'), r.text.lastIndexOf('}') + 1)); } catch (e) { p = null; }
      const reply = p && p.reply, letters = String(reply || '').replace(/[^A-Za-z]/g, '');
      rows.push({ reply, caps_share: letters ? +(letters.replace(/[^A-Z]/g, '').length / letters.length).toFixed(2) : 0,
                  stance: p && p.behaviour && p.behaviour.stance, chase: p && p.behaviour && p.behaviour.drives && p.behaviour.drives.chase,
                  usd: +B.costUsd('nearai', r.usage).toFixed(6) });
    }
    out[kind] = rows;
  }
  console.log(JSON.stringify(out, null, 1));
})();
