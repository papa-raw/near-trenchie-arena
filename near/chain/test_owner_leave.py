"""Wallet-page Leave revokes an agent seat, pairing and its session key.

Run: python3 -B near/chain/test_owner_leave.py
All signing keys are ephemeral and remain in memory; chain reads use the desk fixtures.
"""
import asyncio
import inspect
import json
from pathlib import Path
import sys
import time
import types
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
from near.chain import test_identity_desk as fixtures
from near.chain.test_identity_desk import PREMINT_SHEET, wallet_key
import snap


HTTP = '--http' in sys.argv
if HTTP:
    sys.argv.remove('--http')


class OwnerLeave(unittest.TestCase):
    def setUp(self):
        async def offline_serve(dev, ready):
            ready(dev.port)
        with patch('near.chain.test_identity_desk.free_port', return_value=18735):
            if HTTP:
                fixtures.HostedRoom.setUp(self)
            else:
                import snap_local
                with patch.object(snap_local, 'serve', offline_serve):
                    fixtures.HostedRoom.setUp(self)
        self.addCleanup(self.loop.close)
        self.addCleanup(self.room.pool.shutdown)
        if not HTTP:
            local_call = lambda url, method='GET', body=None, *a, **k: self.post(urlsplit(url).path, body or {}, method)[1]
            calls = patch.object(snap, 'call', local_call)
            calls.start()
            self.addCleanup(calls.stop)
    tearDown = fixtures.HostedRoom.tearDown
    def post(self, path, body, method='POST'):
        if HTTP:
            return fixtures.HostedRoom.post(self, path, body)
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        reply = self.room.route(method, path, raw, '127.0.0.1')
        return asyncio.run(reply) if inspect.isawaitable(reply) else reply

    page = fixtures.HostedRoom.page
    page_for = fixtures.HostedRoom.page_for

    def agent(self):
        sheet = json.loads(PREMINT_SHEET.read_text())
        token = 'preset-2-00'
        self.nft.tokens[token]['digest'] = self.snap_local.sheet_digest(sheet)
        page = self.page()
        status, out = self.post('/dev/identity', page.env('claim', {'preset': 'hunter-lunge'}))
        self.assertEqual(status, 200, out)
        status, out = self.post('/snap/code', page.env('code', {
            'agent': 'codex', 'name': 'Pike', 'preset': 'hunter-lunge', 'sheet': sheet, 'nft_token_id': token}))
        self.assertEqual(status, 200, out)
        code = out['code']
        case = self
        class OfflineTransport:
            def __init__(self, base, who):
                self.cid = None
            def now(self):
                return case.room.round.vnow()
            def request(self, method, target, body=b''):
                return case.post(target, body, method)[1]
            def open_control(self, url):
                reply = case.room.round.arena.control.open_control(ip='127.0.0.1')
                self.cid = reply['connection_id']
                return reply
            def frame(self, cid, body):
                return case.post('/room/control/frame?cid=' + cid, body)[1]
            def drain_private(self, cid):
                return case.room.round.arena.control.drain_private(cid)
            def close(self):
                if self.cid:
                    case.room.round.arena.control.close_control(self.cid)
        opts = {} if HTTP else {'transport_factory': OfflineTransport}
        keeper = snap.Keeper(types.SimpleNamespace(url=f'http://127.0.0.1:{self.port}', name='unused',
            preset='hunter-lunge', spread='40,30,20,10', zero=10, code=code), **opts)
        keeper.start('1')
        self.addCleanup(keeper.transport.close)
        deadline = time.monotonic() + 8
        while token not in self.room.round.arena.sim.state['fighters'] and time.monotonic() < deadline:
            time.sleep(0.05) if HTTP else self.room.round.arena.advance()
        self.assertEqual(self.room.round.arena.sim.state['fighters'][token]['state'], 'alive')
        return page, token, code, keeper

    def test_owner_page_ends_remote_seat_and_all_old_authority(self):
        page, token, code, keeper = self.agent()
        sk, pk = wallet_key()
        self.idc.full_access['other-player.testnet'] = {pk}
        stranger = self.page_for('other-player.testnet', sk, pk)
        status, out = self.post('/dev/identity', stranger.env('leave', {'nft_token_id': token}))
        self.assertEqual(status, 400, out)
        self.assertIn('current wallet owner', out['error'])
        self.assertIn(token, self.room.round.arena.members)
        self.assertIn(code, self.room.codes)
        # A previous owner's still-valid sign-in grants no authority after a transfer.
        self.nft.tokens[token]['owner'] = 'other-player.testnet'
        status, out = self.post('/dev/identity', page.env('leave', {'nft_token_id': token}))
        self.assertEqual(status, 400, out)
        self.assertIn('current wallet owner', out['error'])
        self.assertIn(code, self.room.codes)
        self.nft.tokens[token]['owner'] = fixtures.PLAYER
        forged = page.env('leave', {'nft_token_id': token})
        forged['payload'] = json.dumps({'nft_token_id': 'someone-else'})
        status, out = self.post('/dev/identity', forged)
        self.assertEqual(status, 400, out)
        self.assertIn('not signed', out['error'])
        self.assertIn(code, self.room.codes)
        signed = page.env('leave', {'nft_token_id': token})
        status, out = self.post('/dev/identity', signed)
        self.assertEqual(status, 200, out)  # baseline: unknown op 'leave'
        self.assertEqual((out['state'], out['fighter_id']), ('home', token))
        status, replay = self.post('/dev/identity', signed)
        self.assertEqual(status, 400, replay)
        self.assertIn('already used', replay['error'])
        self.assertNotIn(code, self.room.codes)
        self.assertNotIn(keeper.public_key, self.room.by_key)
        self.assertNotIn(token, self.room.identities)
        with self.assertRaises((snap.SnapRefusal, ValueError, SystemExit)):
            keeper.client.control('renew', {'lease_until': str(keeper.now() + 30000)})
        with self.assertRaises((ValueError, SystemExit)):
            keeper.rejoin(self.room.round_index)
        with self.assertRaises(ValueError):
            self.room.code_status(code, claim=True, address='127.0.0.1')
        deadline = time.monotonic() + 8
        while token in self.room.round.arena.members and time.monotonic() < deadline:
            time.sleep(0.05) if HTTP else self.room.round.arena.advance()
        self.assertNotIn(token, self.room.round.arena.members, 'the existing swim-home path removes the fighter')
        print('owner leave: stranger refused; owner released agent; old renew/rejoin/code refused; fighter home')

    def test_code_log_reports_member_life_and_lease_expiry_sends_a_dead_process_home(self):
        _, token, code, keeper = self.agent()
        arena = self.room.round.arena
        # Isolate the authoritative member counter from the per-spawn sim counter.
        member = arena.members[token]
        original = {k: member[k] for k in ('life_number', 'life_id', 'awaiting_life', 'spawn_pending')}
        arena.members[token]['life_number'] = 7
        arena.members[token]['life_id'] = token + ':life:7'
        arena.members[token]['awaiting_life'] = False
        arena.members[token]['spawn_pending'] = False
        self.assertEqual(self.room.code_log(code)['life'], 8)
        member.update(original)
        # No beats after transport loss: expiry must release without an owner clicking Leave.
        keeper.transport.close()
        deadline = time.monotonic() + 38
        while token in arena.members and time.monotonic() < deadline:
            time.sleep(0.1) if HTTP else arena.advance()
        self.assertNotIn(token, arena.members, 'a dead agent cannot retain a seat past the 30 s lease')
        print('agent lifetime: current life8; disconnected KO retires without stale-slot clock failure; fighter home')


if __name__ == '__main__':
    unittest.main()
