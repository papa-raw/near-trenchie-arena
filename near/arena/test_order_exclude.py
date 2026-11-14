"""New order-exclude cases; baseline 5627fd0, three fighters, 1000 HP each."""
import json
import unittest

from test_order_safety import HERE, arena, behaviour, give, sim


class OrderExclude(unittest.TestCase):
    def test_exclusion_spares_but_still_hits_other_enemy_in_base_and_reflex(self):
        for reflex in (False, True):
            with self.subTest(reflex=reflex):
                game = arena()
                gate = {'target_is_not': ['b'], 'match': 'any', 'distance_under': 12}
                raw = {'v': 1, 'gate': gate}
                if reflex:
                    raw = {'v': 1, 'reflexes': [{'if': {'always': True}, 'then': {'gate': gate}}]}
                give(game, raw)
                a, b, c = (game.state['fighters'][n] for n in ('a', 'b', 'c'))
                game._policy()
                self.assertEqual(a['target'], 'c')
                game._fire_weapon(a, c, game.rules['weapons']['swing'], 3000)
                game.queue_hit('a', 'b', 17)
                game.queue_hit('a', 'c', 17)
                game._damage()
                self.assertEqual(b['hp'], 1000)
                self.assertLess(c['hp'], 1000)
                self.assertFalse(game._may_strike(a, b))

    def test_named_hp_observes_b_while_targeting_c_then_targets_b(self):
        game = arena()
        give(game, {'v': 1, 'target': 'c', 'reflexes': [
            {'if': {'fighter_hp_below_pct': {'who': 'b', 'pct': 30}}, 'then': {'target': 'b'}}]})
        a, b, c = (game.state['fighters'][n] for n in ('a', 'b', 'c'))
        c['hp'] = 10
        b['hp'] = 300
        game._policy()
        self.assertEqual(a['target'], 'c', 'strict threshold; c HP does not fire a b condition')
        self.assertFalse(a['battle_reflexes'][0]['on'])
        b['hp'] = 299
        game._policy()
        self.assertEqual(a['target'], 'b')
        self.assertTrue(a['battle_reflexes'][0]['on'])
        game.state['tick'] += game.rules['behaviour']['reflex_hold_ticks']
        b['state'] = 'bench'
        game._policy()
        self.assertFalse(a['battle_reflexes'][0]['on'], 'off-floor fighter does not satisfy named HP')

    def test_live_named_target_fifteen_tiles_away_is_approached_without_retargeting(self):
        game = arena()
        give(game, {'v': 1, 'target': 'b', 'drives': {'chase': 10}})
        a, b, c = (game.state['fighters'][n] for n in ('a', 'b', 'c'))
        a.update(x=-7500, y=0)
        b.update(x=7500, y=0)
        c.update(x=-8500, y=0)
        before = sim.distance(a, b)
        self.assertEqual(before, 15 * game.rules['tile'])
        for _ in range(20):
            game._policy()
            self.assertEqual(a['target'], 'b')
            a['x'] += a['move_x']
            a['y'] += a['move_y']
            game.state['tick'] += 1
        self.assertLess(sim.distance(a, b), before)

    def test_aliases_resolve_and_receipt_names_exclusions_and_watched_fighter(self):
        roster = [{'id': 'a', 'name': 'Pebble', 'tag': 'Pebble'},
                  {'id': 'b', 'name': 'Bright Sprout', 'tag': 'Sprout'},
                  {'id': 'c', 'name': 'Cloud Ember', 'tag': 'Ember'}]
        raw = {'v': 1, 'gate': {'target_is_not': ['Sprout', 'b']}, 'reflexes': [
            {'if': {'fighter_hp_below_pct': {'who': 'Ember', 'pct': 30}},
             'then': {'target': 'Ember', 'gate': {'target_is_not': ['Sprout']}}}]}
        receipt = behaviour.ack(raw, sim.DEFAULT_RULES, 'a', 1, 200, roster=roster)
        self.assertEqual(receipt['status'], 'applied', receipt)
        plan = receipt['behaviour']
        self.assertEqual(plan['gate']['target_is_not'], ['b'])
        self.assertEqual(plan['reflexes'][0]['if']['fighter_hp_below_pct'], {'who': 'c', 'pct': 30})
        self.assertEqual(plan['reflexes'][0]['then']['gate']['target_is_not'], ['b'])
        self.assertIn('except b', receipt['summary'])
        self.assertIn('c hp < 30%', receipt['summary'])
        self.assertEqual(behaviour.normalise(plan, sim.DEFAULT_RULES, 'a')[0], plan)
        raw['reflexes'][0]['if']['fighter_hp_below_pct']['who'] = 'missing'
        self.assertEqual(behaviour.ack(raw, sim.DEFAULT_RULES, 'a', 1, 200, roster=roster)['status'], 'refused')

    def test_invalid_shapes_are_refused_and_old_rules_stay_unchanged(self):
        old = json.loads((HERE / 'rules/integer-18.json').read_bytes())
        valid = ({'v': 1, 'gate': {'target_is_not': ['b']}},
                 {'v': 1, 'reflexes': [{'if': {'fighter_hp_below_pct': {'who': 'b', 'pct': 30}},
                                      'then': {'target': 'b'}}]})
        for raw in valid:
            self.assertTrue(behaviour.normalise(raw, old, 'a')[2])
        self.assertEqual(sim.digest(old), 'b6b1ec27712436d62da4a395f4108abea1c341797cb9fd43562ba49f0a6ba9c2')
        for value in ('b', [True], ['a'], ['b'] * 16):
            with self.subTest(exclusion=value):
                self.assertTrue(behaviour.normalise({'v': 1, 'gate': {'target_is_not': value}}, sim.DEFAULT_RULES, 'a')[2])
        for value in (30, {'who': 'b'}, {'who': 'any', 'pct': 30}, {'who': 'b', 'pct': True}):
            with self.subTest(hp=value):
                raw = {'v': 1, 'reflexes': [{'if': {'fighter_hp_below_pct': value}, 'then': {'target': 'b'}}]}
                self.assertTrue(behaviour.normalise(raw, sim.DEFAULT_RULES, 'a')[2])


if __name__ == '__main__':
    unittest.main()
