"""Focused integer-19 protect and off-floor regressions; baseline 102ad86."""
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'near/arena'))
import behaviour
import sim


def arena(rules=None):
    game = sim.Sim(731, rules or sim.DEFAULT_RULES)
    for name in ('a', 'b', 'c'):
        game.enqueue(sim.Input(0, 'join', name, 0, {'angle': 0}))
    game._inputs()
    game.state['tick'] = 200
    for index, f in enumerate(game.state['fighters'].values()):
        f.update(x=(index * 700), y=0, hp=1000, max_hp=1000, shield_until=0,
                 attack_at=0, sig_at=99999, direction=0, target=None)
        f['equipped']['weapon'] = 'c-swing'
        game._set_behaviour(f, behaviour.normalise({'v': 1, 'gate': {'never': True}}, game.rules, f['id'])[0])
    return game


def give(game, raw):
    plan, _, refused, _ = behaviour.normalise(raw, game.rules, 'a')
    assert not refused, refused
    game._set_behaviour(game.state['fighters']['a'], plan)


class ProtectSpare(unittest.TestCase):
    def test_protect_and_reflex_spare_ally_in_selection_swing_and_delayed_damage(self):
        for reflex in (False, True):
            with self.subTest(reflex=reflex):
                game = arena()
                raw = {'v': 1, 'drives': {'protect': 10, 'protect_ally': 'b'}}
                if reflex:
                    raw = {'v': 1, 'reflexes': [{'if': {'always': True}, 'then': {'drives': raw['drives']}}]}
                give(game, raw)
                a, b, c = (game.state['fighters'][n] for n in ('a', 'b', 'c'))
                game._policy()
                self.assertEqual(a['target'], 'c')
                # Same swing cone covers both ally b and enemy c.
                weapon = game.rules['weapons']['swing']
                game._fire_weapon(a, c, weapon, 3000)
                # All weapon/projectile/signature damage routes pass queue_hit.
                game.queue_hit('a', 'b', 17)
                game.queue_hit('a', 'c', 17)
                game._damage()
                self.assertEqual(b['hp'], 1000)
                self.assertLess(c['hp'], 1000)
                a['target'] = 'b'
                self.assertFalse(game._may_strike(a, b))


class TargetAway(unittest.TestCase):
    def test_plain_target_fights_nearest_allowed_enemy_and_resumes_on_return(self):
        game = arena()
        give(game, {'v': 1, 'target': 'b', 'drives': {'chase': 10}})
        a, b, c = (game.state['fighters'][n] for n in ('a', 'b', 'c'))
        b.update(state='bench', respawn_at=99999)
        game._policy()
        self.assertEqual(a['target'], 'c')
        game._attacks()
        game._projectiles()
        game._damage()
        self.assertLess(c['hp'], 1000)
        b.update(state='alive', x=15000)
        game._policy()
        self.assertEqual(a['target'], 'b')

    def test_exclusive_target_loots_keeps_clear_and_does_no_other_damage(self):
        game = arena()
        give(game, {'v': 1, 'target': 'b', 'gate': {'target_is': 'b'}, 'drives': {'chase': 10}})
        a, b, c = (game.state['fighters'][n] for n in ('a', 'b', 'c'))
        b.update(state='bench', respawn_at=99999)
        game.drop_item('c-beam', -3000, 0, None, True)
        game._policy()
        self.assertIsNone(a['target'])
        self.assertLess(a['move_x'], 0, 'loot and keep away from c while b is absent')
        game.queue_hit('a', 'c', 17)
        game._damage()
        self.assertEqual(c['hp'], 1000)
        b.update(state='alive', x=15000)
        game._policy()
        self.assertEqual(a['target'], 'b')


class RulesCompatibility(unittest.TestCase):
    def test_integer18_keeps_old_selection_and_refuses_new_exclusive_gate(self):
        old = json.loads((HERE / 'rules/integer-18.json').read_bytes())
        game = arena(old)
        give(game, {'v': 1, 'drives': {'protect': 10, 'protect_ally': 'b'}})
        game._policy()
        self.assertEqual(game.state['fighters']['a']['target'], 'b')
        give(game, {'v': 1, 'target': 'b'})
        game.state['fighters']['b']['state'] = 'bench'
        game._policy()
        self.assertIsNone(game.state['fighters']['a']['target'])
        self.assertTrue(behaviour.normalise({'v': 1, 'gate': {'target_is': 'b'}}, old, 'a')[2])
        self.assertEqual(sim.digest(old), 'b6b1ec27712436d62da4a395f4108abea1c341797cb9fd43562ba49f0a6ba9c2')

    def test_exclusive_alias_and_any_match_cannot_admit_other_fighters(self):
        roster = [{'id': 'a', 'name': 'Pebble', 'tag': 'Pebble'},
                  {'id': 'b', 'name': 'Bright Sprout', 'tag': 'Sprout'}]
        ack = behaviour.ack({'v': 1, 'target': 'Sprout', 'gate': {'target_is': 'Sprout',
                             'match': 'any', 'distance_under': 12}}, sim.DEFAULT_RULES, 'a', 1, 200, roster=roster)
        self.assertEqual(ack['status'], 'applied', ack)
        self.assertEqual(ack['behaviour']['gate']['target_is'], 'b')
        game = arena()
        game._set_behaviour(game.state['fighters']['a'], ack['behaviour'])
        game._policy()
        game.queue_hit('a', 'c', 17)
        game._damage()
        self.assertEqual(game.state['fighters']['c']['hp'], 1000)
        self.assertIn('only b', ack['summary'])


if __name__ == '__main__':
    unittest.main()
