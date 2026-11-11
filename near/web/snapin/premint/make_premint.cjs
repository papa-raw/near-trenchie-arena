// make_premint.cjs: the five premint personas, one per battle option, built with the guide's own sheet.js.
// A premint token carries one persona digest fixed at mint; claim(token, to, persona_hash) must name that same digest, so
// these five sheets are fixed files, never rebuilt in a page. A first-come player who claims an option gets that persona.
//   node near/web/snapin/premint/make_premint.cjs [path/to/emoji-set.js]
// writes near/web/snapin/premint/<role>.json (the sheets: exactly what `check_personas.py --dir` reads), and in meta/:
// <role>.look.json (the look travels beside the sheet) and options.json: exactly the five battle-option ids, each
// {file, digest, option, look, name, role, temperament, emoji} (file = a sheet at premint/'s top; digest = check_personas --digest).
// Each sheet's tag is the persona's first name, one plain word with no digits (Barnacle, Pike, ...).
// Deterministic: the same definitions give the same bytes and digests. Check with:
//   python3 -I near/lore/check_personas.py --dir near/web/snapin/premint      (prints "5/5 valid")
//   python3 -I near/lore/check_personas.py --digest near/web/snapin/premint/<role>.json   (equals options.json)
'use strict';
const fs = require('fs'), path = require('path');
const HERE = __dirname, SNAP = path.resolve(HERE, '..');
const E = require(process.argv[2] ? path.resolve(process.argv[2]) : path.join(SNAP, 'emoji-set.js'));
globalThis.SnapEmoji = E;   // sheet.js writes game.emoji only for a set these rules accept
const SS = require(path.join(SNAP, 'sheet.js'));

// the look of each option's preset portrait in the guide's grid (app.js PRESET_LOOK, the approved S3 c parts)
const LOOKS = [
  { shape: 'bean', body: 'p07', tone: 'warm', eyes: 'keen', brows: 'none', mouth: 'smile', hair: 'cowlick', hairCol: 'p03', hat: 'st-cap' },
  { shape: 'pear', body: 'p15', tone: 'warm', eyes: 'sleepy', brows: 'none', mouth: 'smile', hair: 'puffs', hairCol: 'p03', hat: 'st-cap' },
  { shape: 'pebble', body: 'p12', tone: 'warm', eyes: 'happy', brows: 'none', mouth: 'smile', hair: 'fin', hairCol: 'p03', hat: 'st-cap' },
  { shape: 'bean', body: 'p07', tone: 'warm', eyes: 'keen', brows: 'none', mouth: 'smile', hair: 'none', hairCol: 'p03', hat: 'st-cap' },
  { shape: 'pear', body: 'p12', tone: 'warm', eyes: 'sleepy', brows: 'none', mouth: 'smile', hair: 'cowlick', hairCol: 'p03', hat: 'st-cap' }
];
// five house-made newcomers, washed up with the rest after the Great Rug; one per battle option, five temperaments
const PERSONAS = [
  { preset: 'brawler-swing', name: 'Barnacle Bertie', temperament: 'gruff', quirks: ['mutters'],
    voice: 'Swings first and argues later. Is sure every crab on the island owes it money.',
    lines: ['Oar’s up. Who’s next?', 'That one was for the crabs.', 'Back of the line.'] },
  { preset: 'hunter-lunge', name: 'Pike Pennywhistle', temperament: 'restless', quirks: ['hums'],
    voice: 'Cannot sit still. Lunges at anything that twitches and whistles when it lands one.',
    lines: ['Saw you twitch. Here I come!', 'Whee! Got one!', 'Too slow, too slow, too slow.'] },
  { preset: 'survivor-beam', name: 'Lantern Lou', temperament: 'serene', quirks: ['weather'],
    voice: 'Calm as low tide. Keeps a lamp lit and a beam ready for anyone who crowds the light.',
    lines: ['Easy now. Mind the beam.', 'The tide always comes back.', 'Clear skies, light swell, one less rival.'] },
  { preset: 'looter-lob', name: 'Coconut Cass', temperament: 'sunny', quirks: ['sea-puns'],
    voice: 'Lobs coconuts and compliments in equal measure, and pockets anything that glints.',
    lines: ['Incoming! Sorry! Not sorry!', 'Ooh, shiny. Mine now, thank you!', 'Shell yeah!'] },
  { preset: 'brawler-zap', name: 'Static Sid', temperament: 'deadpan', quirks: ['counts-kos'],
    voice: 'Says zap instead of hello. Unimpressed by everything, thunder included.',
    lines: ['Zap.', 'That was the plan.', 'Three. Not that I am counting.'] }
];

(async () => {
  const meta = path.join(HERE, 'meta'); fs.mkdirSync(meta, { recursive: true });
  const order = SS.PRESETS.map((p) => p.id), options = {};
  let bad = 0;
  for (const d of PERSONAS) {
    const i = order.indexOf(d.preset);
    const state = { name: d.name, tag: d.name.split(' ')[0], temperament: d.temperament, quirks: d.quirks, voice: d.voice, lines: d.lines, preset: d.preset, look: LOOKS[i], door: '', emoji: E.DEFAULTS[d.temperament] };
    const g = SS.guard(d.name); if (!g.ok) { bad++; console.log('GUARD', d.name, g.reason); }
    const sheet = SS.build(state), fails = SS.validate(sheet);
    if (fails.length) { bad++; console.log('INVALID', d.name, fails.join(' | ')); }
    if (!sheet.game.emoji) { bad++; console.log('NO EMOJI', d.name, E.checkSet(E.DEFAULTS[d.temperament])); }
    const role = sheet.identity.role, file = role + '.json';
    fs.writeFileSync(path.join(HERE, file), JSON.stringify(sheet, null, 1) + '\n');
    fs.writeFileSync(path.join(meta, role + '.look.json'), JSON.stringify(SS.lookFile(state), null, 1) + '\n');
    const dg = await SS.digest(sheet);
    options[d.preset] = { file: file, digest: dg, option: SS.PRESETS[i].name, look: 'meta/' + role + '.look.json', name: sheet.game.name, role, temperament: sheet.game.temperament,
      temper: d.temperament, quirks: d.quirks, voice: d.voice, emoji: sheet.game.emoji };   // what the guide prefills when the option is claimed
    console.log(`${d.preset.padEnd(14)} ${file.padEnd(24)} ${dg}`);
  }
  // exactly the five battle-option keys at the top (the mainnet kit's contract): option -> {file, digest, ...}
  fs.writeFileSync(path.join(meta, 'options.json'), JSON.stringify(options, null, 1) + '\n');
  process.exit(bad ? 1 : 0);
})();
