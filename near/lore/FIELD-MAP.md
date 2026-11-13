# Field map: the Trenchie persona sheet

A persona is one JSON file in the format [persona.schema.json](persona.schema.json) describes: ten core elements and one optional, versioned `game` block. The sheet is the package. A harness renders it and never writes it. Any agent harness can read the same format; none is required.

## Files and how they are made

| File | What it is | Made by |
|---|---|---|
| `kits.json` | the 14 kit rows, the item table, the rivals and the alliances | `python3 -I near/lore/gen_kits.py` |
| `personas/<trenchieId>.json` × 14 | the house sheets; the `game` cosmetics are copied from `kits.json` | `python3 -I near/lore/gen_personas.py` (run after gen_kits) |
| `persona.schema.json` | the format, with a description on every element and field | by hand |
| `check_personas.py` | the checker: schema, arena rules, house rules, the digest | `--selftest` breaks copies on purpose (50 checks) |
| `check_sheets.py` | the kit-table checker `check_personas.py` calls | `--kits`, `--selftest` |
| `LORE.md` | the lore bible: the Great Rug, the coin, the welcome, the six temperaments, the 14 | by hand; the checker confirms it names every tag and legendary |

Edit the generators, never the generated files. Each generator says so in its header.

## The ten core elements

| Element | What it holds for a Trenchie | Who reads it |
|---|---|---|
| `identity` | role id, the brief (lore, myth, beef, arena rules), personality, mark, assessor, the clause against text that gives it goals, coordination role, handoff | the house runtime builds the prompt prefix from it |
| `tools` | the six arena intents: `intent-focus`, `intent-avoid`, `intent-loot`, `intent-sig`, `intent-leave`, `intent-say`. The model never moves the body. | the runtime offers exactly these |
| `skills`, `libraries`, `hooks` | empty for an arena fighter | the checker refuses any entry on an arena sheet |
| `memory` | every pool `not built`; none is carried on a sale | the checker |
| `model_routing` | a compatibility envelope. The operator's pane choice decides the model; this block is outside the digest | the operator |
| `permissions` | no network, no files; `tool_subset` equals the six intents | the checker |
| `manifest` | name, dated version, the elements held (`game` exactly when present) | the checker |
| `self_improvement` | declared disabled for arena fighters, plus one runnable check | the checker |

## The `game` block (version 2)

Version 2: the arena's own game block. A sheet that says version 1 is refused. Public data only. It names no tool, command, path, permission or memory, and carries no number except `version` and the legendary's `serial`.

| Key | Meaning |
|---|---|
| `name`, `tag` | the full name on the card; the short tag over the head and in the feed (one word, except Banana Zone) |
| `loadout` | house sheets only: `rares` (three rares plus the legendary trinket) or `commons` (the legendary plus three commons). Seven each. |
| `temperament` | one of six: Sunny, Deadpan, Earnest, Gruff, Serene, Restless. None is a fight-style word. |
| `emoji` | 5 to 8 single emoji its AI picks from when it speaks, one per line; the picked one floats over its fighter for about 3 s and leads its line in the ticker. They fit its temperament and its running joke. Required on the 14 house sheets. A creator's sheet may leave it out: it then uses its temperament's default set (`emoji_defaults.json`), and its lines say so. Rules: `emoji.py`. |
| `voice` | three sample lines, at most 60 characters each |
| `tics`, `banned_registers`, `never_hooks` | habits, registers it never uses, topics it never raises |
| `belief` | `{myth, line}`: which off-island myth it blames for the Great Rug (`silent_dev`, `faceless_whale`, `rogue_bot`). Never a Trenchie. |
| `rivalries` | seeded rivals and allies, equal to the pairs in `kits.json` |
| `fight_style`, `preset` | one of brawler, hunter, looter, guardian, survivor; the preset equals it at version 2 |
| `cosmetics` | palette ids, the named legendary (`id`, `name`, `reskin_of`, `serial`), the starter kit, the signature piece. A declaration, never an inventory grant: the chain owns the real bag. |
| `reactions` | four keyed lines: `ko_by_rival`, `lost_legendary`, `missed_prediction`, `hit_prediction`. They are also the labelled fallback when a banter reroll still repeats or the budget stops. |

The runtime sends `temperament`, `tics`, `never_hooks`, `banned_registers`, `belief`, the rivalries, `voice` and the emoji set in the prompt. The checker caps that rendering at 600 characters, about 150 tokens (the ratio is an estimate).

## The content digest

`python3 -I near/lore/check_personas.py --digest FILE` prints a sha256 over the sheet without `model_routing` and `manifest`. A change of model, provider or effort leaves it equal. A change to the identity, the rules, the tools, the permissions or the game block moves it, and that is a different persona.

## Limits

- The persona text (briefs, myths, voice, tics, reactions) is original lore.
- The 600-character render cap and the 60-character line cap are working numbers. The banter tests recalibrate them.
- The 14 are spoofs. Every public line passes the output check.
