"""One restart/duplicate regression, with the real Arena/Sim and an in-memory inventory boundary."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from near.arena import server, sim  # noqa: E402
from near.chain import batch  # noqa: E402
from near.chain.writer import ChainWriter  # noqa: E402

ITEM = 'leg-lifeboat'


class Inventory:
    label = 'serial-fixture'

    def __init__(self):
        self.bags = {}

    def view(self, receiver, method, args=None):
        args = args or {}
        if method == 'trenchie':
            bag = self.bags.get(args['token_id'])
            return None if bag is None else {'bag': copy.deepcopy(bag), 'record': None}
        raise AssertionError((receiver, method, args))

    def apply(self, token, bag):
        """The deployed NFT's serial uniqueness predicate; no network/signing boundary is exercised."""
        for e in bag:
            if e['serial'] and any(other != token and any(
                    (x['row'], x['serial']) == (e['row'], e['serial']) for x in rows)
                    for other, rows in self.bags.items()):
                raise ValueError('serial already on another bag')
        self.bags[token] = copy.deepcopy(bag)


def writer(directory, inventory):
    cfg = SimpleNamespace(arena='arena.fixture.testnet', market='market.fixture.testnet',
                          nft='inventory.fixture.testnet', identity_nft='identity.fixture.near')
    w = ChainWriter(inventory, cfg, directory, identity=inventory, log=lambda _: None)
    w.state['pool'] = [[0, i, i + 1] for i in range(4)]
    return w


def arena(directory, w):
    return server.Arena({'rules_hash': sim.digest(sim.DEFAULT_RULES), 'deployment_id': 'serial-fixture'},
                        [1], data_dir=directory, chain=w)


def grab(a, token):
    game = a.sim
    game.enqueue(sim.Input(0, 'join', token, 0, {'house': False, 'angle': 0}))
    game._inputs()
    f = game.state['fighters'][token]
    f.update(x=0, y=0, last_damage_tick=-1)
    game.drop_item(ITEM, 0, 0, None, True, origin='ko')
    for _ in range(game.rules['grab_ticks']):
        game._grabs()
        game.state['tick'] += 1
    return f['bag'][ITEM]


class RestartSerial(unittest.TestCase):
    def test_unknown_inventory_rows_do_not_break_startup_or_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Inventory()
            w = writer(Path(tmp), inventory)
            known = {'row': w.item_rows.index(ITEM), 'serial': 7,
                     'born_batch': 0, 'hands': 1, 'kos': 0, 'flags': 0}
            unknown = [dict(known, row=-1, serial=50),
                       dict(known, row=len(w.item_rows) + 5, serial=60)]
            bag = unknown + [known]
            # Startup migrates saved bags and both forms of base, including pre-floor states.
            w.state['bags']['absent'] = copy.deepcopy(bag)
            w.state['bases']['absent'] = {'bag': copy.deepcopy(bag), 'arena': copy.deepcopy(bag), 'at': 'load'}
            w.state.pop('serials')
            w._save()
            w = writer(Path(tmp), inventory)
            self.assertEqual(w.state['serials'], {ITEM: 7})
            self.assertEqual(w.state['bags']['absent'], bag, 'unknown chain entries remain intact')
            # The same path is called when process drains an inventory refresh.
            refreshed = unknown + [dict(known, serial=8)]
            w.inbox.append({'kind': 'inventory_loaded', 'token': 'arriving',
                            'bag': refreshed, 'arena': [], 'kept': unknown})
            w.state['synced'] = True
            w.lookahead = 2  # The fixture's four reserved seeds need no network top-up.
            w.process()
            self.assertEqual(w.state['serials'], {ITEM: 8})
            self.assertEqual(w.state['bases']['arriving']['bag'], refreshed)

    def test_new_round_never_reuses_an_inactive_or_historically_reserved_serial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = Inventory()
            w = writer(root/'chain', inventory)
            row = w.item_rows.index(ITEM)
            old = {'row': row, 'serial': 1, 'born_batch': 0, 'hands': 1, 'kos': 0, 'flags': 0}
            inventory.bags['absent-fighter'] = [old]
            w.state['bags']['absent-fighter'] = [old]
            w.state['bases']['absent-fighter'] = {'bag': [old], 'arena': [old], 'at': 'filed'}
            w._save()
            # Baseline: fresh rounds start at zero; the absent chain holder never joins to seed their counter.
            w = writer(root/'chain', inventory)
            first = arena(root/'round-1', w)
            entry = grab(first, 'new-fighter')
            try:
                inventory.apply('new-fighter', [dict(entry, row=row)])
            except ValueError as exc:
                self.fail(str(exc) + ': fresh round allocated %s, already held by absent-fighter' % entry['serial'])
            self.assertEqual(entry['serial'], 2, 'one historical serial requires the next distinct copy')
            self.assertEqual(inventory.bags['absent-fighter'], [old], 'the real old copy stays with its holder')
            # No seal yet: another round in this same process must reserve the just-issued number too.
            second = arena(root/'round-2', w)
            self.assertEqual(grab(second, 'next-fighter')['serial'], 3)
            self.assertEqual(second.initial_state['serials'][ITEM], 2, 'the floor is part of replay initial state')
            # A complete seal carries counters even when a copy has left every bag (burned/floor loss).
            sealed = {'seed': '1', 'seed_hash': batch.seed_hash(1), 'sealed_result_hash': '0'*64,
                      'inputs_hash': '0'*64, 'rules_hash': sim.digest(sim.DEFAULT_RULES),
                      'final_state_hash': '0'*64, 'predictions_log_hash': '0'*64,
                      'lives': [], 'nft_token_ids': []}
            w.sealed(second, 'segment:0', {'sealed': sealed, 'predictions': []})
            w._drain()
            self.assertEqual(w.state['serials'][ITEM], 3, 'a sealed counter survives with no bag entries')
            w._save()
            restarted = writer(root/'chain', inventory)
            third = arena(root/'round-3', restarted)
            self.assertEqual(grab(third, 'last-fighter')['serial'], 4)
            # Legacy migration also reserves historical copies that no current bag holds.
            state = json.loads(restarted.state_path.read_text())
            state.pop('serials')
            restarted.state_path.write_text(json.dumps(state))
            historic = dict(old, serial=20)
            (root/'chain/batches.jsonl').write_text(json.dumps({'rows': [{'bag': [historic]}]})+'\n')
            migrated = writer(root/'chain', inventory)
            fourth = arena(root/'round-4', migrated)
            self.assertEqual(grab(fourth, 'migrated-fighter')['serial'], 21)


if __name__ == '__main__':
    unittest.main()
