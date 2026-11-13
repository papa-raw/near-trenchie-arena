"""A stale house pursuit yields to a reachable opponent through the real behaviour bridge.

Only the new case runs; its model is scripted and all state changes are local fixtures.
"""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'arena'), str(HERE.parents[1])]
import behaviour
import test_battle as helpers
import test_live


class StalePursuit(unittest.TestCase):
    def test_house_retargets_without_touching_players_or_interrupting_useful_chase(self):
        with tempfile.TemporaryDirectory() as data:
            clock = [20_000 * 86400]
            comp, arena, house, _, orders = helpers.compose(data, clock, mode='building')
            try:
                test_live.run(arena, clock, 300)
                rt, sim = house.runtime, arena.sim
                rt.pending.clear()
                rt.budget.allow = lambda *args: False  # retargeting spends no model call
                names = sorted(n for n, f in sim.state['fighters'].items() if f['state'] == 'alive')
                self.assertGreaterEqual(len(names), 3)
                me, old, near = names[:3]
                f, target, other = (sim.state['fighters'][n] for n in (me, old, near))
                for n in names[3:]:
                    sim.state['fighters'][n]['state'] = 'bench'
                f.update(x=0, y=0, cast=None)
                target.update(x=8000, y=0)
                other.update(x=1000, y=0)
                f['equipped']['weapon'] = 'c-swing'
                sim._stats(f)
                plan = {'v': 1, 'stance': 'hunt-weakest', 'gate': {}, 'target': old,
                        'reflexes': [{'if': {'enemy_within': 10}, 'then': {'target': old}}]}
                normalized, _, refused, _ = behaviour.normalise(plan, sim.rules, me)
                self.assertFalse(refused)

                def reset():
                    sim._set_behaviour(f, copy.deepcopy(normalized))
                    f['battle_reflexes'][0]['on'] = True
                    f.update(target=old, target_since=sim.state['tick'])
                    rt.battle.behaviour[me] = copy.deepcopy(normalized)
                    rt.battle.planned.add(me)
                    sim.state['events'] = []

                reset()
                # An owner-controlled fighter can be visible to the runtime, but has no house sheet.
                owner = copy.deepcopy(f)
                owner['id'] = 'visitor'
                owner['house'] = False
                owner['x'] = 20000
                sim.state['fighters']['visitor'] = owner
                owner_before = copy.deepcopy(owner)
                calls_before = rt.stats['calls']
                count = len(orders)
                rt._battle_poll({'active': [me, 'visitor']}, clock[0])
                self.assertEqual(len(orders), count + 1, 'a reachable alternative produces one house order')
                sent = orders[-1][1]
                self.assertEqual(sent['target'], near)
                self.assertEqual(sent['reflexes'][0]['then']['target'], near, 'an active named-target reflex cannot restore stale pursuit')
                self.assertEqual(sent['gate'], normalized['gate'], 'retargeting does not open a closed gate')
                self.assertEqual(sim.state['fighters']['visitor'], owner_before)
                self.assertEqual(rt.stats['calls'], calls_before)
                # The bridge records the order; its input must be accepted, not a direct sim mutation.
                self.assertTrue(any(c['kind'] == 'input' and c['value'].get('kind') == 'behaviour'
                                    and c['value'].get('fighter_id') == me for c in arena.commands))
                self.assertIn(me, rt.engage_notes, 'the correction is visible on the house status')

                # No repeated orders while the first is still travelling through the bridge.
                rt._battle_poll({'active': [me]}, clock[0])
                self.assertEqual(len(orders), count + 1)

                # A useful approach with no closer eligible opponent is left alone.
                sim.state['tick'] += 100
                clock[0] += 5
                other.update(x=11000, y=0)
                target.update(x=7000, state='alive')
                reset()
                count = len(orders)
                for _ in range(8):
                    rt._battle_poll({'active': [me]}, clock[0])
                    sim.state['tick'] += 20
                    clock[0] += 1
                    target['x'] -= 400
                self.assertEqual(len(orders), count, 'closing distance is useful pursuit')

                # A non-closing out-of-range target is released for a closer alternative after six seconds.
                other['x'] = 3000
                target['x'] = 7000
                reset()
                count = len(orders)
                rt._battle_poll({'active': [me]}, clock[0])
                sim.state['tick'] += 120
                clock[0] += 6
                rt._battle_poll({'active': [me]}, clock[0])
                self.assertEqual(len(orders), count + 1)
                self.assertEqual(orders[-1][1]['target'], near)

                # Even with no closer alternative, an unchanged ten-second pursuit must yield.
                sim.state['tick'] += 100
                clock[0] += 5
                other['x'] = 11000
                target['x'] = 7000
                reset()
                count = len(orders)
                rt._battle_poll({'active': [me]}, clock[0])
                sim.state['tick'] += 200
                clock[0] += 10
                rt._battle_poll({'active': [me]}, clock[0])
                self.assertEqual(len(orders), count + 1, 'ten seconds without attacking releases the target')
                self.assertEqual(orders[-1][1]['target'], near)

                # A vanished named target is released even when the sim already cleared f.target.
                sim.state['tick'] += 100
                clock[0] += 5
                reset()
                target['state'] = 'bench'
                f['target'] = None
                count = len(orders)
                rt._battle_poll({'active': [me]}, clock[0])
                self.assertEqual(len(orders), count + 1)
                self.assertNotEqual(orders[-1][1]['target'], old)
            finally:
                comp.tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
