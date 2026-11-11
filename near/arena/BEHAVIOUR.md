# Battle mode: behaviour schema v1

A fighter's AI (an agent session, a browser brain or the house runtime) never steers its fighter
directly. It sends a **behaviour**: a small JSON plan the arena runs every tick until the AI sends
another one. A behaviour persists across respawns. Everything in it is whitelisted integers, booleans
and short strings, it is logged as an input, and it replays exactly under its rules table.

The arena checks every behaviour and answers with one **ACK frame**: what it applied, what it clipped
and what it refused, the tick it applies at, and one plain summary line.

Validator and receipt code: `near/arena/behaviour.py` (`normalise`, `ack`, `summary`). The engine:
`near/arena/sim.py`, input kind `behaviour`, from rules table `integer-13`.

## 1. The behaviour

```json
{
  "v": 1,
  "stance": "loot",
  "drives": {"loot": 10, "keep_away": 8, "keep_away_radius": 5, "chase": 3},
  "gate": {"target_hp_below_pct": 40, "target_busy": true},
  "target": "weakest",
  "reflexes": [
    {"if": {"self_hp_below_pct": 25}, "then": {"stance": "flee", "say": "Not today."}},
    {"if": {"hit_recently": true}, "then": {"gate": {}, "target": "attacker"}}
  ]
}
```

Every key except `v` is optional. A new behaviour **replaces** the previous one whole; it is never
merged. `{"v": 1, "clear": true}` drops the behaviour and hands the fighter back to its style's
default AI.

| Key | Values | Meaning |
|---|---|---|
| `v` | `1` | Schema version. Required. |
| `stance` | `flee`, `berserk`, `defend`, `loot`, `hold`, `follow-ally`, `hunt-weakest` | A named preset (section 4). Applied first; `drives`, `gate` and `target` override it key by key. |
| `drives` | object, below | How the fighter moves. |
| `gate` | object, below | Who the fighter may attack. `{}` = any enemy. |
| `target` | `auto`, `nearest`, `weakest`, `attacker`, or a fighter id | How it picks among the enemies the gate lets through. Default `auto`. |
| `reflexes` | list of at most 8 | Ordered "if this, then that" overrides. |
| `clear` | `true` | Only with `v`: drop the behaviour. |

### Drives (each 0 to 10; 0 = off)

| Key | Range | Meaning |
|---|---|---|
| `loot` | 0–10 | Walk to the best grabbable drop in view (higher tier and nearer first). When loot is the strongest active drive the fighter stands on the drop until it is grabbed (6 undamaged ticks). |
| `keep_away` | 0–10 | Walk away from every enemy inside `keep_away_radius`: one at the edge pushes at half strength, one touching at full. The enemy the fighter is attacking does not push. |
| `keep_away_radius` | 1–12 tiles (default 4) | |
| `chase` | 0–10 | Walk toward the attack target until it is in weapon reach. With no target in view, walk toward the nearest enemy anywhere on the ring that passes the gate (from rules table integer-14, `behaviour.chase_seek`; under integer-13 the fighter stands until an enemy comes into view). |
| `protect` | 0–10 | Stay within 3 tiles of `protect_ally`; enemies that hit the ally in the last 3 s score higher as targets. Needs `protect_ally`. |
| `protect_ally` | fighter id | |
| `hold` | 0–10 | Walk back into the hold area whenever outside it. |
| `hold_at` | `"center"`, `"here"`, or `{"x_milli": int, "y_milli": int}` (default `"center"`) | `"here"` is where the fighter stands on the tick the behaviour (or the reflex) takes effect. Coordinates are the same milli-tiles the observe call shows. |
| `hold_radius` | 1–6 tiles (default 2) | |

Each active drive pulls with its weight and the pulls add up. The arena still pushes fighters off the
edge, apart in a crowd, and sideways out of an incoming shot, beam or lob. With every drive at 0 the
fighter stands its ground and fights only what the gate lets come into reach.

### Attack gate

The gate decides which enemies may be attacked. Weapons and the offensive signatures (beam sweep,
chain storm, shockwave, blink strike) fire only at a target that passes. Shields and the dodge roll are
never gated. Shockwave also fires in self-defence, as before: own hp below its threshold with an
enemy in trigger range.

The gate is a promise, not only an aim: a fighter on a behaviour damages only the enemies its gate
lets through at the moment the hit lands. A swing cone, a zap chain, a shot, a beam or an area
signature passes harmlessly over everyone else.

| Key | Range | Passes when |
|---|---|---|
| `match` | `"all"` (default) or `"any"` | all listed conditions hold, or at least one |
| `never` | `true` | never: the fighter attacks no one, not even in self-defence (v1.1; other conditions are dropped with a note) |
| `target_hp_below_pct` | 1–99 | the enemy's hp is below this % of its max |
| `target_busy` | `true` / `false` | the enemy is fighting someone else (its target is another fighter) or faces away from you (more than 90° off) |
| `distance_under` | 1–12 tiles | the enemy is nearer than this |
| `rival` | `true` / `false` | the enemy is one of the fighter's seeded rivals |
| `wears_legendary` | `true` / `false` | the enemy wears a legendary item |

A `false` value is the same as leaving the condition out.

### Target

`target` chooses among the enemies that pass the gate and are in view (12 tiles; seeded rivals
anywhere on the ring, as before):

- `auto`: the style's own scoring, including a `focus` order (rules table focus weight) and the bounty.
- `nearest`, `weakest` (lowest hp %), `attacker` (whoever hit the fighter last, while that enemy passes the gate).
- a fighter id: that fighter, while it passes the gate and is in view.

Ties break by fighter id. When nothing passes, the fighter has no target and attacks no one.

### Reflexes (at most 8)

Each reflex is `{"if": {<one condition>}, "then": {<one or more actions>}}`. Every tick, each reflex
whose condition holds lays its `then` over the behaviour; when the condition stops holding the
override goes away. Once a reflex turns on or off it stays that way for at least 1 s, so a condition
on a boundary cannot flicker. **Reflex 1 has the highest priority**: where two active reflexes set the
same field, the lower number wins. "The current attack target" in a condition is the one chosen on
the previous tick.

Conditions (exactly one per `if`):

| Condition | Range | Holds when |
|---|---|---|
| `self_hp_below_pct` | 1–99 | own hp is below this % |
| `self_hp_above_pct` | 1–99 | own hp is above this % |
| `enemy_within` | 1–12 tiles, or `{"radius": 1–12, "who": "any" \| "rival" \| "ally_attacker" \| <id>}` (v1.1) | an enemy (of that kind) is nearer than this; `ally_attacker` = one that hit `protect_ally` in the last 3 s |
| `enemies_at_least` | `{"count": 2–15, "radius": 1–12}` | at least `count` enemies are within `radius` tiles |
| `hit_recently` | `true` | the fighter was hit in the last 3 s |
| `ally_hit_recently` | `true` | `protect_ally` was hit in the last 3 s |
| `loot_within` | 1–12 tiles | a drop the fighter can grab is nearer than this |
| `legendary_on_floor` | `true` | a legendary the fighter can grab lies within view |
| `target_hp_below_pct` | 1–99 | the current attack target's hp is below this % |
| `no_target` | `true` | no enemy passes the gate |
| `always` | `true` | always (v1.1) |
| `hit_by` | `{"who": "any" \| "rival" \| <id>}` | the fighter was hit by that one in the last 3 s (v1.1) |

Actions (at least one per `then`):

| Action | Value | Effect while the reflex holds |
|---|---|---|
| `stance` | a stance name | lays the stance's drives, gate and target down first |
| `drives` | a partial drives object | overrides just those drives |
| `gate` | a gate object (`{}` = any) | replaces the gate |
| `target` | a target mode | replaces the target mode |
| `say` | text, at most 80 characters, one line | sent once when the reflex turns on; the host guards it like every feed line, and the 10 s speech limit applies |
| `repeat` | `true`, only beside `say` | the line is said again every time the fighter's 10 s window opens, for as long as the reflex holds (v1.1) |

Every on/off change is reported as an event (at most one per reflex per second, by the 1 s hold); a
fighter's `say` lines fire at most once per 10 s.

### Schema v1.1 (additive)

v1.1 adds the gate's `never`, the conditions `always` and `hit_by`, `enemy_within`'s `who` form and the
`repeat` action; `v` stays `1` and every v1 behaviour means what it meant. The rules table carries
`behaviour.schema_minor: 1`. Pat's critbee ("run away from everyone, don't attack anyone, scream in caps
every time you can"):

```json
{"v": 1, "stance": "flee", "gate": {"never": true},
 "reflexes": [{"if": {"always": true}, "then": {"say": "AAAA RUN", "repeat": true}}]}
```

With `never` there is no attack target, so `keep_away` pushes from every enemy. A live AI that writes a
fresh line each window speaks through the host's speech frame; the 10 s window it waits for is the
host's feed cap, which the engine does not see, so `speech_ready` is a host event, not an engine one.

## 2. Limits

| Limit | Value |
|---|---|
| Orders (behaviours and intents share one clock) | one per 0.5 s per fighter (rules `intent_interval` 10 ticks) |
| Reflexes | 8 |
| Behaviour size | 2048 bytes as canonical JSON |
| `say` | 80 characters, printable, one line |
| Fighter ids (`protect_ally`, `target`) | 1–64 characters |

## 3. Clipped, refused, notes

**Refused** (nothing changes; the previous behaviour keeps running): not a JSON object; `v` missing or
not 1; an unknown key; a wrong type; an unknown stance, condition, action or target mode; a reflex
without exactly one condition or with no action; `protect` above 0 or `follow-ally` without
`protect_ally`; `protect_ally` or `target` naming the fighter itself; `clear` with other keys; over
2048 bytes; an order sooner than 0.5 s after the last one.

**Clipped** (applied, with each change listed): a number out of range is set to the nearest limit
("keep_away_radius 40 > max 12 tiles: set to 12"); more than 8 reflexes keeps the first 8; a `say` over 80
characters is cut to 80; a `hold_at` point off the ring is pulled onto its edge.

**Notes** (applied as sent): an ally or target id that is not in the ring now ("protect_ally
dev-bee is not in the ring now; protect waits for it"); every drive at 0.

## 4. Stance presets (rules table `behaviour.stances`)

| Stance | loot | keep_away (radius) | chase | protect | hold (radius) | gate | target |
|---|---|---|---|---|---|---|---|
| `flee` | 2 | 10 (8) | 0 | 0 | 0 | distance under 2 | nearest |
| `berserk` | 0 | 0 | 10 | 0 | 0 | any | nearest |
| `defend` | 0 | 0 | 3 | 0 | 8 here (3) | distance under 5 | attacker |
| `loot` | 10 | 6 (4) | 1 | 0 | 0 | hp below 30% | weakest |
| `hold` | 0 | 0 | 2 | 0 | 10 here (2) | distance under 6 | nearest |
| `follow-ally` | 0 | 0 | 4 | 10 | 0 | any | auto |
| `hunt-weakest` | 1 | 0 | 10 | 0 | 0 | any | weakest |

`follow-ally` needs `drives.protect_ally`. A stance only fills in values; keys sent next to it win.

Pat's example, "grab all the loot and run away from others, only attack when they're low on HP and
not paying attention":

```json
{"v": 1, "drives": {"loot": 10, "keep_away": 8, "keep_away_radius": 5, "chase": 3},
 "gate": {"target_hp_below_pct": 40, "target_busy": true}}
```

## 5. The ACK frame (host to the session, one per behaviour order)

```json
{"type": "behaviour_ack", "v": 1, "fighter": "dev-bee", "seq": 12,
 "status": "clipped",
 "receive_tick": 18400, "apply_tick": 18402, "applies_in_ms": 100,
 "behaviour": {"...": "the normalised behaviour exactly as logged, or null when refused"},
 "clipped": [{"path": "drives.keep_away_radius", "sent": 40, "set": 12,
              "fix": "keep_away_radius 40 > max 12 tiles: set to 12"}],
 "refused": [],
 "notes": [],
 "summary": "New behaviour recorded: loot 10 · keep_away 8 (radius 12, clipped from 40) · chase 3 · attack gate: hp below 40% and busy · target auto · no reflexes · applies at tick 18,402 (in 0.1 s) · persists across respawns",
 "rules_hash": "<the table's sha256>"}
```

- `status`: `applied` (as sent), `clipped` (applied with the listed changes), `refused` (nothing
  changed; `refused` lists every problem, each with a `fix`).
- A refused summary reads: "Refused: reflexes[2].if: unknown condition 'hp_low'; use one of
  self_hp_below_pct, … · nothing changed; your last behaviour stays".
- The host signs the frame as it signs every input receipt, and logs `behaviour` (the normalised form)
  as the input. The engine accepts only the normalised form, so a replay never re-runs a clip.
- The engine confirms on the apply tick with an event: `{"kind": "behaviour", "fighter": id}`, or
  `{"kind": "intent_refused", "fighter": id}` if the order clock refused it.

Other engine events: `{"kind": "reflex", "fighter": id, "index": i, "on": true|false}` (i counts from 1) and
`{"kind": "say", "fighter": id, "index": i, "text": "..."}` (the host guards the text before any feed
shows it).

The in-character reply to the owner is the AI's own, never the host's; the receipt is the host's,
shown verbatim.
