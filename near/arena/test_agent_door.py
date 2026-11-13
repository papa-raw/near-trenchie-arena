"""Creator sheets, authenticated speech and real door pairing on the DEV host."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(os.environ["SNAP_CASE_ROOT"]) / "near/arena") if "SNAP_CASE_ROOT" in os.environ else str(HERE))
import snap
import snap_local
from test_snap_local import LocalSnap, StickyOrders, new_public_key


def creator_sheet() -> dict:
    sheet = json.loads((HERE.parent / 'lore/personas/vitrenchik.json').read_text())
    sheet['identity']['role'] = sheet['manifest']['name'] = 'pebble-skipper'
    sheet['game'] = dict(version=2, name='Pebble Skipper', tag='Pebble', temperament='Serene',
                         voice=['One ripple at a time.', 'A calm shore.', 'Still afloat.'], tics=[],
                         fight_style='hunter', cosmetics=dict(palette=['p09', 'p11']),
                         reactions=dict(ko_by_rival='A ripple.', lost_legendary='It floats away.',
                                        missed_prediction='A wider ripple.', hit_prediction='Still water.'))
    return sheet


class AgentDoor(unittest.TestCase):
    setUp = LocalSnap.setUp
    shutdown = LocalSnap.shutdown
    # Reuse only the fixture, never the inherited suite.
    def test_creator_sheet_is_checked_bound_and_projected_without_private_core(self) -> None:
        sheet = creator_sheet()
        ident = self.dev.create_identity('pebble', 'hunter', new_public_key(), sheet=sheet)
        self.assertEqual(ident['name'], 'Pebble Skipper')
        public_name = self.dev.profile({'nft_token_id': ident['nft_token_id'], 'account_id': ident['account_id']})['public_name']
        self.assertIn('DEV Pebble Skipper', public_name)
        if not ident['name_checked']:
            self.assertIn('name unchecked', public_name)
        rec = self.dev.identities[ident['nft_token_id']]
        self.assertEqual(rec['persona']['temperament'], 'Serene')
        self.assertEqual(rec['persona']['paletteIds'], ['p09', 'p11'])
        self.assertNotIn('tools', rec['persona'])
        broken = copy.deepcopy(sheet)
        broken['permissions']['sandbox']['network'] = ['https://invalid.example']
        with self.assertRaisesRegex(ValueError, 'sheet'):
            self.dev.create_identity('broken', 'hunter', new_public_key(), sheet=broken)
        bad_name = copy.deepcopy(sheet)
        bad_name['game']['name'] = 'fraud'
        with self.assertRaisesRegex(ValueError, 'name'):
            self.dev.create_identity('blocked', 'hunter', new_public_key(), sheet=bad_name)

    def test_real_code_is_not_joined_by_registration_and_cannot_be_reused(self) -> None:
        status, issued = self.dev.route('POST', '/snap/code', json.dumps({'agent': 'codex', 'name': 'Pebble Skipper', 'sheet': creator_sheet(), 'preset': 'hunter'}).encode(), '127.0.0.1')
        self.assertEqual(status, 200, issued)
        code = issued['code']
        self.assertFalse(issued.get('stub', False))
        before = self.dev.route('GET', '/snap/code/' + code, b'', '127.0.0.1')[1]
        self.assertFalse(before['joined'])
        ident = self.dev.create_identity('', 'hunter', new_public_key(), code=code)
        self.assertFalse(self.dev.route('GET', '/snap/code/' + code, b'', '127.0.0.1')[1]['joined'])
        with self.assertRaisesRegex(ValueError, 'code'):
            self.dev.create_identity('', 'hunter', new_public_key(), code=code)
        self.dev.round.arena.members[ident['nft_token_id']] = {'binding': {'session_key_id': 'key'}}
        self.dev.mark_paired(ident['nft_token_id'])
        self.assertTrue(self.dev.route('GET', '/snap/code/' + code, b'', '127.0.0.1')[1]['joined'])
        self.dev.round.arena.members.pop(ident['nft_token_id'])

    def test_code_waits_for_real_signed_room_authentication(self) -> None:
        import types
        issued = self.dev.issue_code(dict(agent="codex", name="Pebble Skipper", sheet=creator_sheet(), preset="hunter"))
        keeper = snap.Keeper(types.SimpleNamespace(url=self.url, name="unused", preset="hunter", spread="40,30,20,10", zero=10, code=issued["code"]))
        target = "/snap/code/" + issued["code"]
        self.assertFalse(self.dev.route("GET", target, b"", "127.0.0.1")[1]["joined"])
        keeper.start("1")
        paired = self.dev.route("GET", target, b"", "127.0.0.1")[1]
        self.assertEqual((paired["state"], paired["fighter_id"]), ("joined", keeper.token))
        self.assertEqual(self.dev.identities[keeper.token]["name"], "Pebble Skipper")

    def test_cli_creator_join_state_and_say_from_empty_folder(self) -> None:
        import subprocess
        import time
        from near.house.guard import Guard
        self.dev.feed.guard = Guard(dict(names=[], handles=[], slurs=[]), [])
        sheet = Path(self.tmp.name) / "pebble-skipper.json"
        sheet.write_text(json.dumps(creator_sheet()))
        command = [sys.executable, "-I", str(Path(snap.__file__)), "--url", self.url]
        def run(*args: str) -> dict:
            out = subprocess.run(command + list(args), cwd=self.tmp.name, capture_output=True, text=True, timeout=90)
            log = Path(self.tmp.name) / ".snap-dev.log"
            self.assertEqual(out.returncode, 0, out.stderr + (log.read_text() if log.exists() else ""))
            return json.loads(out.stdout.splitlines()[0])
        try:
            joined = run("join", "--sheet", str(sheet), "--preset", "hunter", "--accept-terms", "1")
            self.assertTrue(joined["joined"])
            deadline = time.monotonic() + 30
            while run("state")["you"]["state"] != "ring":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.1)
            said = run("intent", "--say", "One ripple at a time.")
            self.assertEqual(said["speech"]["text"], "One ripple at a time.")
        finally:
            subprocess.run(command + ["stop"], cwd=self.tmp.name, capture_output=True, timeout=20)

    def speaker(self, *, missing: bool = False) -> snap.Keeper:
        import types
        import time
        from near.house.guard import Guard
        self.dev.feed.guard = Guard(None if missing else dict(names=[], handles=[], slurs=[]), [])
        keeper = snap.Keeper(types.SimpleNamespace(url=self.url, name="speaker", preset="hunter", spread="40,30,20,10", zero=10))
        keeper.start("1")
        deadline = time.monotonic() + 30
        while keeper.summary()["you"]["state"] != "ring":
            self.assertLess(time.monotonic(), deadline)
            keeper.tick()
            time.sleep(.1)
        self.dev.round.arena.sim.state["fighters"][keeper.token]["hp"] = 100000  # isolate feed cadence from combat KOs
        return keeper

    def test_signed_speech_is_guarded_and_rate_limited(self) -> None:
        keeper = self.speaker()
        accepted = keeper.intent({"say": "One ripple at a time."})
        self.assertEqual(accepted["speech"]["text"], "One ripple at a time.")
        self.assertEqual(len(self.dev.feed.since()), 1)
        again = keeper.intent({"say": "Another ripple."})
        self.assertEqual(again["speech"]["refused"], "rate_limited", again)
        self.assertEqual(len(self.dev.feed.since()), 1)

    def test_signed_blocked_speech_becomes_an_emote(self) -> None:
        keeper = self.speaker()
        blocked = keeper.intent({"say": "fraud"})
        self.assertTrue(blocked["speech"]["blocked"], blocked)
        self.assertNotIn("fraud", json.dumps(self.dev.feed.public()))

    def test_signed_speech_without_a_list_is_muted_and_labelled(self) -> None:
        keeper = self.speaker(missing=True)
        muted = keeper.intent({"say": "A calm shore."})
        self.assertTrue(muted["speech"]["muted"], muted)
        self.assertEqual(muted["speech"]["label"], "guard list missing")



class DoorLive(unittest.TestCase):
    """The guide's one-time code gives the agent battle mode on the creator's trenchie, not one-shot orders."""
    setUp = LocalSnap.setUp
    shutdown = LocalSnap.shutdown

    def test_a_door_code_starts_a_live_battle_session_on_the_same_trenchie_and_join_with_a_code_is_refused(self) -> None:
        import subprocess
        import time
        status, issued = self.dev.route('POST', '/snap/code', json.dumps({'agent': 'claude-code', 'name': 'Pebble Skipper', 'sheet': creator_sheet(), 'preset': 'survivor-beam'}).encode(), '127.0.0.1')
        self.assertEqual(status, 200, issued)
        code = issued['code']
        self.assertIn(f' live --code {code} ', issued['command'])  # main: `join --code`, the one-shot client
        self.assertIn('--fifo', issued['command'])
        command = [sys.executable, '-I', str(Path(snap.__file__)), '--url', self.url]
        refused = subprocess.run(command + ['join', '--code', code, '--preset', 'hunter', '--accept-terms', '1'],
                                 cwd=self.tmp.name, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('live --code', refused.stderr + refused.stdout)
        self.assertEqual(self.dev.route('GET', '/snap/code/' + code, b'', '127.0.0.1')[1]['state'], 'pending', 'a refused join leaves the code unspent')
        fifo = Path(self.tmp.name) / 'orders.fifo'
        live = subprocess.Popen(command + ['live', '--code', code, '--preset', 'hunter', '--accept-terms', '1', '--fifo', str(fifo), '--seconds', '60'],
                                cwd=self.tmp.name, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def end_live() -> None:
            if live.poll() is None:
                live.kill()
            live.communicate(timeout=20)
        self.addCleanup(end_live)
        events = []
        def until(kind: str) -> dict:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                line = live.stdout.readline()
                if not line:
                    self.fail('live ended: ' + live.stderr.read()[-2000:])
                events.append(json.loads(line))
                if events[-1]['kind'] in (kind, 'refusal'):
                    return events[-1]
            self.fail(f'no {kind} within 45 s: {events[-3:]}')
        ready = until('session_ready')
        self.assertEqual(ready['kind'], 'session_ready', ready)
        paired = self.dev.route('GET', '/snap/code/' + code, b'', '127.0.0.1')[1]
        self.assertEqual((paired['state'], paired['fighter_id']), ('joined', ready['fighter_id']))
        self.assertEqual(self.dev.identities[ready['fighter_id']]['name'], 'Pebble Skipper')
        self.assertEqual(self.dev.identities[ready['fighter_id']]['preset'], 'survivor-beam', "the code's preset, not the CLI's")
        self.assertEqual(until('life_start')['kind'], 'life_start')  # an order before the life starts is refused
        # The owner said "run away from everyone": the agent writes that as a behaviour.
        with open(fifo, 'w') as orders:
            orders.write(json.dumps({'v': 1, 'stance': 'flee', 'gate': {'never': True}}) + '\n')
        ack = until('ack')
        self.assertEqual(ack['kind'], 'ack', ack)
        receipt = ack['receipt']
        self.assertEqual(receipt['nft_token_id'], ready['fighter_id'], 'the order lands on the paired trenchie')
        self.assertIn(receipt['ack']['status'], ('applied', 'clipped'), receipt['ack'])
        self.assertTrue(receipt['ack']['summary'] and ack['summary'] == receipt['ack']['summary'])


class DoorNotes(unittest.TestCase):
    """The agent door's owner panel: after an order's ACK the agent's note (the order in the owner's words, its reply in
    the trenchie's voice, and why) reaches GET /snap/code/<code>/log as one kept note joined to that order's receipt,
    and a plan line shows the plan's weekly compute share."""
    setUp = LocalSnap.setUp
    shutdown = LocalSnap.shutdown

    def test_a_note_after_an_order_joins_its_receipt_in_the_owner_log_and_the_plan_shows_the_weekly_share(self):
        import subprocess
        import time
        status, issued = self.dev.route('POST', '/snap/code', json.dumps({'agent': 'claude-code', 'name': 'Bob', 'preset': 'hunter'}).encode(), '127.0.0.1')
        code = issued['code']
        fifo = Path(self.tmp.name) / 'orders.fifo'
        live = subprocess.Popen([sys.executable, '-I', str(Path(snap.__file__)), '--url', self.url, 'live', '--code', code, '--preset', 'hunter',
                                 '--accept-terms', '1', '--fifo', str(fifo), '--seconds', '60'],
                                cwd=self.tmp.name, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def end_live() -> None:
            if live.poll() is None:
                live.kill()
            live.communicate(timeout=20)
        self.addCleanup(end_live)
        events = []
        def until(kind: str) -> dict:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                line = live.stdout.readline()
                if not line:
                    self.fail('live ended: ' + live.stderr.read()[-2000:])
                events.append(json.loads(line))
                if events[-1]['kind'] in (kind, 'refusal'):
                    return events[-1]
            self.fail(f'no {kind} within 45 s: {events[-3:]}')
        until('session_ready')
        self.assertEqual(until('life_start')['kind'], 'life_start')
        with open(fifo, 'w') as orders:
            orders.write(json.dumps({'v': 1, 'stance': 'flee', 'gate': {'never': True}}) + '\n')
            orders.flush()
            ack = until('ack')
            self.assertEqual(ack['receipt']['ack']['status'], 'applied', ack)
            seq = ack['receipt']['sequence']
            # The note names no seq: the client joins it to the last order it sent.
            orders.write(json.dumps({'note': {'order': 'bob run away from everyone',
                                              'reply': 'Legs first, questions later.',
                                              'why': 'Flee stance and a never gate: keep away from everyone, attack no one.'}}) + '\n')
            orders.flush()
            kept = until('ack')
            self.assertEqual(kept['receipt']['kind'], 'note')
            self.assertEqual(kept['receipt']['ack']['status'], 'kept', kept)
            orders.write(json.dumps({'plan': {'week_used_pct': 4}}) + '\n')
            orders.flush()
            self.assertEqual(until('ack')['receipt']['ack']['status'], 'kept')
        log = self.dev.route('GET', f'/snap/code/{code}/log', b'', '127.0.0.1')[1]
        rows = [r for r in log['log'] if r['kind'] == 'order' and r['seq'] == seq]
        self.assertEqual(len(rows), 1, log['log'])
        row = rows[0]
        self.assertEqual((row['order'], row['reply']), ('bob run away from everyone', 'Legs first, questions later.'))
        self.assertIn('never gate', row['why'])
        self.assertEqual(row['receipt']['status'], 'applied', 'the note sits beside the order it answers')
        self.assertEqual(log['plan']['week_used_pct'], 4)


class DoorPlanStop(unittest.TestCase):
    """The subscription door's own stop: the door sets a share of the plan's week (5, 10 or 20%); the live session reads
    it with its code and, once its reported weekly share reaches it, sends no more orders and says so."""
    setUp = LocalSnap.setUp
    shutdown = LocalSnap.shutdown

    def test_a_session_sends_orders_under_its_weekly_limit_and_none_once_it_is_reached(self):
        import subprocess
        import time
        status, issued = self.dev.route('POST', '/snap/code', json.dumps({'agent': 'claude-code', 'name': 'Bob', 'preset': 'hunter',
                                                                          'plan_stop_pct': 5}).encode(), '127.0.0.1')
        self.assertEqual(status, 200, issued)
        code = issued['code']
        fifo = Path(self.tmp.name) / 'orders.fifo'
        live = subprocess.Popen([sys.executable, '-I', str(Path(snap.__file__)), '--url', self.url, 'live', '--code', code, '--preset', 'hunter',
                                 '--accept-terms', '1', '--fifo', str(fifo), '--seconds', '60'],
                                cwd=self.tmp.name, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def end_live() -> None:
            if live.poll() is None:
                live.kill()
            live.communicate(timeout=20)
        self.addCleanup(end_live)
        events = []
        def until(*kinds: str) -> dict:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                line = live.stdout.readline()
                if not line:
                    self.fail('live ended: ' + live.stderr.read()[-2000:])
                events.append(json.loads(line))
                if events[-1]['kind'] in kinds + ('refusal',):
                    return events[-1]
            self.fail(f'no {kinds} within 45 s: {events[-3:]}')
        ready = until('session_ready')
        self.assertEqual(ready.get('plan_stop_pct'), 5, 'the session read its door limit')
        until('life_start')
        def orders_logged() -> int:
            log = self.dev.route('GET', f'/snap/code/{code}/log', b'', '127.0.0.1')[1]
            return sum(1 for r in log['log'] if r['kind'] == 'order' and r['receipt'] is not None)
        with open(fifo, 'w') as orders:
            def send(value) -> None:
                orders.write(json.dumps(value) + '\n')
                orders.flush()
            send({'v': 1, 'stance': 'flee'})
            self.assertEqual(until('ack')['receipt']['ack']['status'], 'applied')
            send({'plan': {'week_used_pct': 3}})
            self.assertEqual(until('ack')['receipt']['ack']['status'], 'kept')
            time.sleep(0.6)                                              # one order per 0.5 s
            send({'v': 1, 'stance': 'loot'})
            self.assertEqual(until('ack')['receipt']['ack']['status'], 'applied', 'under the limit, orders go')
            self.assertEqual(orders_logged(), 2)
            send({'plan': {'week_used_pct': 5}})
            stop = until('plan_stop')
            self.assertEqual(stop['kind'], 'plan_stop', stop)
            self.assertEqual(stop['summary'], 'weekly limit reached: 5% of 5%; your Trenchie fights on its last plan')
            time.sleep(0.6)
            send({'v': 1, 'stance': 'berserk'})
            refused = until('ack')
            self.assertEqual((refused['kind'], refused.get('code'), refused.get('sent')), ('refusal', 'plan_stop', False), refused)
            send({'note': {'why': 'still talking to my owner'}})
            self.assertEqual(until('ack')['receipt']['ack']['status'], 'kept', 'notes still reach the panel')
            self.assertEqual(orders_logged(), 2, 'no order reached the arena after the limit')
            plan = self.dev.route('GET', f'/snap/code/{code}/log', b'', '127.0.0.1')[1]['plan']
            self.assertEqual((plan['stop_pct'], plan['week_used_pct'], plan['stopped']), (5, 5, True))
            behaviour = self.dev.round.arena.sim.state['fighters'][ready['fighter_id']]['behaviour']
            self.assertEqual(behaviour['drives']['loot'], 10, 'the trenchie fights on its last plan (loot), not the refused berserk')
            # A new week: the session reports a share under the limit again, and orders go again.
            send({'plan': {'week_used_pct': 1}})
            resumed = until('plan_resumed')
            self.assertEqual(resumed['summary'], 'weekly share back under the limit: 1% of 5%; orders go again')
            time.sleep(0.6)
            send({'v': 1, 'stance': 'berserk'})
            self.assertEqual(until('ack')['receipt']['ack']['status'], 'applied')
        self.assertEqual(orders_logged(), 3)
        plan = self.dev.route('GET', f'/snap/code/{code}/log', b'', '127.0.0.1')[1]['plan']
        self.assertEqual((plan['week_used_pct'], plan['stopped']), (1, False))


class SayWire(unittest.TestCase):
    def test_non_json_proxy_refusal_names_the_fix_without_echoing_body(self) -> None:
        import io
        import urllib.error
        from unittest.mock import patch
        refused = urllib.error.HTTPError("http://127.0.0.1:8765/room/observe", 403, "Forbidden", {}, io.BytesIO(b"a private proxy detail"))
        with patch.object(snap.urllib.request, "urlopen", side_effect=refused):
            with self.assertRaises(SystemExit) as caught:
                snap.call("http://127.0.0.1:8765/room/observe")
        self.assertIn("HTTP 403", str(caught.exception))
        self.assertIn("allowed route", str(caught.exception))
        self.assertNotIn("private proxy detail", str(caught.exception))

    def test_say_is_sent_once_and_not_reapplied_next_life(self) -> None:
        k = StickyOrders().keeper()
        k.send_orders(k.client.fighters[0], k.client.observe(), k.orders, False, 'One ripple at a time.')
        self.assertEqual(k.client.sent[-1]['say'], 'One ripple at a time.')
        k.life_id = 'life:1'
        k.orders['focus'] = 'nearest'
        k.reapply_orders()
        self.assertIsNone(k.client.sent[-1]['say'])


if __name__ == '__main__':
    unittest.main()
