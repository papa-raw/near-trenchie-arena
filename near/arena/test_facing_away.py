"""Facing-only gates through validation, selection and shared damage paths."""
import json
from pathlib import Path
import unittest

import behaviour
import sim
from test_order_safety import arena


class FacingAway(unittest.TestCase):
    def test_facing_only_selects_and_hits_away_enemy_even_when_other_is_busy(self):
        game = arena()
        raw = {'v': 1, 'stance': 'berserk', 'gate': {'target_facing_away': True}}
        receipt = behaviour.ack(raw, game.rules, 'a', 1, 200)
        self.assertEqual(receipt['status'], 'applied', receipt)
        self.assertIn('facing away', receipt['summary'])
        game._set_behaviour(game.state['fighters']['a'], receipt['behaviour'])
        a, b, c = (game.state['fighters'][n] for n in ('a', 'b', 'c'))
        # Both enemies are inside one swing; b faces a while fighting c.
        b.update(x=700, y=0, direction=180, target='c')
        c.update(x=1000, y=0, direction=0, target=None)
        game._policy()
        self.assertEqual(a['target'], 'c')
        self.assertFalse(game._may_strike(a, b))
        self.assertTrue(game._may_strike(a, c))
        game._attacks()
        game._damage()
        self.assertEqual(b['hp'], 1000)
        self.assertLess(c['hp'], 1000)
        # The condition is checked again when damage is queued, after a turn.
        hp = c['hp']
        c['direction'] = 180
        game.queue_hit('a', 'c', 17)
        game._damage()
        self.assertEqual(c['hp'], hp)

    def test_boundaries_reflexes_false_and_released_rules(self):
        game = arena()
        a, b = (game.state['fighters'][n] for n in ('a', 'b'))
        b.update(x=1000, y=0, target='c')
        gate = {'match': 'all', 'target_facing_away': True}
        for direction, allowed in ((0, True), (90, False), (180, False), (270, False)):
            b['direction'] = direction
            self.assertEqual(game._passes(a, b, gate, 1000, {'b': 'c'}), allowed)
        for layer in ({'gate': gate}, {'reflexes': [{'if': {'always': True}, 'then': {'gate': gate}}]}):
            receipt = behaviour.ack({'v': 1, **layer}, game.rules, 'a', 1, 200)
            self.assertEqual(receipt['status'], 'applied', receipt)
            plan = receipt['behaviour']
            self.assertEqual(behaviour.normalise(plan, game.rules, 'a')[0], plan)
        false = behaviour.ack({'v': 1, 'gate': {'target_facing_away': False}}, game.rules, 'a', 1, 200)
        self.assertEqual(false['status'], 'applied')
        self.assertNotIn('target_facing_away', false['behaviour']['gate'])
        old = json.loads((Path(__file__).parent / 'rules/integer-18.json').read_text())
        self.assertEqual(behaviour.ack({'v': 1, 'gate': gate}, old, 'a', 1, 200)['status'], 'refused')
        self.assertEqual(sim.digest(old), 'b6b1ec27712436d62da4a395f4108abea1c341797cb9fd43562ba49f0a6ba9c2')
        table = json.loads((Path(__file__).parent / 'rules/integer-19.json').read_text())
        self.assertEqual(sim.digest(table), sim.digest(sim.DEFAULT_RULES))


if __name__ == '__main__':
    unittest.main()
