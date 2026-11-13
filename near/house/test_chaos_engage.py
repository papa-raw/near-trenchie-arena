"""Five low-HP house fighters keep fighting in lean mode; only this new case is run by the builder."""
import collections
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'arena'), str(HERE.parents[1])]
import test_house_engage as fixture
import behaviour

SECONDS = 45                     # stays inside one immutable segment; fixture HP changes are not replay inputs


class ChaosEngage(unittest.TestCase):
    def test_five_low_hp_house_fighters_keep_attacking_in_lean_mode(self):
        cleared, notes = fixture.battle.engage({'v': 1, 'clear': True}, {}, fixture.sim.DEFAULT_RULES)
        self.assertNotIn('clear', cleared, 'a house clear cannot restore the cautious default tick policy')
        cleared_plan, _, refused, _ = behaviour.normalise(cleared, fixture.sim.DEFAULT_RULES, 'avichad')
        self.assertFalse(refused)
        self.assertEqual(cleared_plan['drives']['chase'], 10)
        self.assertTrue(notes)
        with tempfile.TemporaryDirectory() as data:
            comp, arena, house, clock, orders = fixture.lean_ring(data, copy.deepcopy(fixture.LIVE_PLANS))
            try:
                # Isolate the engagement rewrite from any separately built stale-pursuit policy.
                house.runtime._retarget = lambda name: False
                fixture.run(arena, clock, 10)
                self.assertEqual(house.runtime.battle.style, 'lean')
                log_path = Path(data) / 'house/behaviours.jsonl'
                self.assertTrue(log_path.exists(), house.runtime.notes)
                logged = [json.loads(l) for l in log_path.read_text().splitlines()]
                self.assertTrue(all(r['status'] in ('applied', 'clipped') for r in logged), logged)
                self.assertTrue(all(arena.sim.state['fighters'][n]['behaviour'] is not None for n in fixture.LIVE_PLANS))
                names = sorted(fixture.LIVE_PLANS)
                original_plans = copy.deepcopy(fixture.LIVE_PLANS)
                attacks = collections.Counter()
                no_target = collections.Counter()
                longest = collections.Counter()
                no_target_runs = collections.Counter()
                movement = {}
                moving_runs = collections.Counter()
                moving_episodes = []
                lives = set()
                for _ in range(SECONDS * 20):
                    # Every new life starts low, reproducing the all-red-HP stalemate without preventing KOs/respawns.
                    for name in names:
                        f = arena.sim.state['fighters'].get(name)
                        if f and f['state'] == 'alive' and (name, f['life_id']) not in lives:
                            lives.add((name, f['life_id']))
                            f['hp'] = min(f['hp'], max(1, f['max_hp'] // 5))
                    arena.advance(1)
                    clock[0] = round(clock[0] + .05, 2)
                    state = arena.sim.state
                    fired = {e['fighter'] for e in state['events'] if e['kind'] == 'attack'}
                    attacks.update(fired)
                    alive = [f for f in state['fighters'].values() if f['state'] == 'alive']
                    for name in names:
                        f = state['fighters'].get(name)
                        active = f is not None and f['state'] == 'alive'
                        missing = active and len(alive) > 1 and f['target'] is None
                        no_target[name] = no_target[name] + 1 if missing else 0
                        longest[name] = max(longest[name], no_target[name])
                        if no_target[name] == 21:
                            no_target_runs[name] += 1
                        # Same maximal moving/no-weapon-attack classifier as sliding-diag, >1 milli-tile/tick and >20 ticks.
                        old = movement.get(name)
                        moved = active and old and old[2] == f['life_id'] and (f['x'] - old[0]) ** 2 + (f['y'] - old[1]) ** 2 > 1
                        if moved and name not in fired:
                            moving_runs[name] += 1
                        else:
                            if moving_runs[name] > 20:
                                moving_episodes.append({'id': name, 'seconds': moving_runs[name] / 20})
                            moving_runs[name] = 0
                        movement[name] = (f['x'], f['y'], f['life_id']) if active else None
                moving_episodes.extend({'id': n, 'seconds': t / 20} for n, t in moving_runs.items() if t > 20)
                metrics = {'seconds': SECONDS, 'house_fighters': names, 'battle_style': house.runtime.battle.style,
                           'attacks': dict(attacks), 'attacks_per_fighter_minute': {n: round(attacks[n] * 60 / SECONDS, 3) for n in names},
                           'longest_no_target_seconds': {n: longest[n] / 20 for n in names},
                           'no_target_stretches_over_1s': dict(no_target_runs), 'moving_no_attack_stretches': moving_episodes}
                print(json.dumps(metrics, sort_keys=True))
                if os.environ.get('CHAOS_EVIDENCE'):
                    Path(os.environ['CHAOS_EVIDENCE']).write_text(json.dumps(metrics, indent=2) + '\n')
                self.assertEqual(fixture.LIVE_PLANS, original_plans, 'the model fixtures are not mutated')
                self.assertTrue(all(attacks[n] >= 3 for n in names), 'every low-HP house fighter attacks repeatedly')
                self.assertTrue(all(longest[n] <= 80 for n in names), 'no house fighter lacks a target for over four seconds while enemies live')
                # A cautious reflex cannot reinstate avoidance after the base plan engages.
                for name, raw in orders:
                    for layer in [raw] + [r['then'] for r in raw.get('reflexes', [])]:
                        if 'drives' in layer:
                            self.assertEqual([layer['drives'].get(k, 0) for k in ('loot', 'keep_away', 'hold', 'protect')], [0, 0, 0, 0])
                        self.assertFalse(set(layer.get('gate', {})) - {'match'}, 'all house layers allow an enemy through')
            finally:
                comp.tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
