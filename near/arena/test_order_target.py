"""Focused cases for host aliases and selection before target reflexes."""
import json
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]
import behaviour
import sim
from test_battle_protocol import joined_room


class OrderTarget(unittest.TestCase):
    def test_host_resolves_names_and_tags_before_logging_the_plan(self):
        with joined_room() as (dev, keeper):
            arena = dev.round.arena
            for name in ('Sailor', 'LASER SAILOR', 'LASER-SAILOR'):
                ack = keeper.client.control('behaviour', {'v': 1, 'target': name,
                    'drives': {'protect': 2, 'protect_ally': 'Moonwood'},
                    'reflexes': [{'if': {'always': True}, 'then': {'target': 'Laser Sailor',
                        'drives': {'protect_ally': 'Kathie Moonwood'}}}]}, life_id=keeper.life_id)['ack']
                self.assertEqual(ack['status'], 'applied', ack)
                self.assertEqual(ack['behaviour']['target'], 'laser-sailor')
                self.assertEqual(ack['behaviour']['drives']['protect_ally'], 'kathie-moonwood')
                self.assertEqual(ack['behaviour']['reflexes'][0]['then']['target'], 'laser-sailor')
                self.assertEqual(ack['behaviour']['reflexes'][0]['then']['drives']['protect_ally'], 'kathie-moonwood')
                self.assertIn('Laser Sailor (laser-sailor)', ack['summary'])
                arena.advance(10)
            before = arena.store.index
            bad = keeper.client.control('behaviour', {'v': 1, 'target': 'Unknown Sprout'}, life_id=keeper.life_id)['ack']
            self.assertEqual(bad['status'], 'refused')
            self.assertIn('Laser Sailor', bad['summary'])
            self.assertIn('valid', bad['summary'].lower())
            self.assertEqual(arena.store.index, before, 'unknown names do not enqueue or replace a plan')
            roster = dev.route('GET', '/house/targets', b'', '127.0.0.1')[1]
            self.assertIn({'id': 'laser-sailor', 'name': 'Laser Sailor', 'tag': 'Sailor'},
                          [{k: row[k] for k in ('id', 'name', 'tag')} for row in roster])
            aliases = [{'id': 'me', 'name': 'Pebble', 'tag': 'Pebble'},
                       {'id': 'one', 'name': 'Dune One', 'tag': 'Dune'},
                       {'id': 'two', 'name': 'Dune Two', 'tag': 'Dune'}]
            for target, code in [('Dune', 'ambiguous_fighter'), ('PEBBLE', 'self')]:
                refused = behaviour.ack({'v': 1, 'target': target}, arena.sim.rules, 'me', 1, 100, roster=aliases)
                self.assertEqual(refused['status'], 'refused')
                self.assertEqual(refused['refused'][0]['code'], code)

    def test_reflex_hp_uses_the_new_target_and_old_rules_keep_the_previous_tick(self):
        old = json.loads((Path(__file__).parent / 'rules/integer-17.json').read_bytes())
        old_bytes = (Path(__file__).parent / 'rules/integer-17.json').read_bytes()
        new = json.loads((Path(__file__).parent / 'rules/integer-18.json').read_bytes())
        self.assertTrue(sim.DEFAULT_RULES['behaviour']['reflex_target_current'])
        self.assertEqual({k for k in new if new[k] != old.get(k)}, {'version', 'behaviour'})
        self.assertEqual({k for k in new['behaviour'] if new['behaviour'][k] != old['behaviour'].get(k)}, {'reflex_target_current'})
        for rules, corrected in ((sim.DEFAULT_RULES, True), (old, False)):
            for old_hp, new_hp in ((20, 100), (100, 20)):
                with self.subTest(version=rules['version'], old_hp=old_hp):
                    game = sim.Sim(5, rules)
                    for index, name in enumerate(('a', 'b', 'c')):
                        game.enqueue(sim.Input(0, 'join', name, 0, {'angle': index * 120}))
                    game._inputs(); game.state['tick'] = 200
                    for index, f in enumerate(game.state['fighters'].values()):
                        f.update(x=index * 1000, y=0, hp=100, max_hp=100, shield_until=0, target=None)
                    a, b, c = (game.state['fighters'][name] for name in ('a', 'b', 'c'))
                    b['hp'], c['hp'], a['target'] = old_hp, new_hp, 'b'
                    plan = behaviour.normalise({'v': 1, 'target': 'c', 'drives': {'chase': 10},
                        'reflexes': [{'if': {'target_hp_below_pct': 29}, 'then': {'gate': {'never': True}}}]}, rules, 'a')[0]
                    game._set_behaviour(a, plan); game._policy()
                    self.assertEqual(a['battle_reflexes'][0]['on'], (new_hp if corrected else old_hp) < 29)
        self.assertEqual((Path(__file__).parent / 'rules/integer-17.json').read_bytes(), old_bytes)


if __name__ == '__main__':
    unittest.main()
