"""New lost-accepted-admission regression; no prior test method is invoked."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]

from near.onboarding.test_recovery import ArrivalRecovery
from near.onboarding import arrival
from room.policy import canonical_bytes
from snap_client import SnapRefusal


class LostJoinReply(unittest.TestCase):
    def test_exact_pending_join_recovers_after_lost_accepted_reply(self) -> None:
        setup = ArrivalRecovery()
        setup.setUp()
        self.addCleanup(setup.doCleanups)
        flow, client, room = setup.real_client('/never-drop')
        fixture = setup.fixture
        underlying = client._transport

        class InterruptedReply:
            def __init__(self) -> None:
                self.posts: list[bytes] = []
                self.challenge_calls = 0
                self.manifest_calls = 0

            def request(self, method: str, target: str, body: bytes = b'') -> dict:
                if target == '/room':
                    self.manifest_calls += 1
                if target == '/room/challenge':
                    self.challenge_calls += 1
                reply = underlying.request(method, target, body)
                if target != '/room/join':
                    return reply
                self.posts.append(body)
                attempt = len(self.posts)
                if attempt == 2:
                    changed = deepcopy(reply)
                    changed['request_digest'] = '0' * 64
                    changed['signature'] = room.sign(canonical_bytes(changed, exclude=('signature',)))
                    return changed
                if attempt == 3:
                    return dict(reply, signature='B' * 85 + 'A')
                if attempt < 4:
                    raise OSError('synthetic lost accepted join response')
                return reply

            def open_control(self, url: str) -> dict:
                return underlying.open_control(url)

            def frame(self, cid: str, body: bytes) -> dict:
                return underlying.frame(cid, body)

            def drain_private(self, cid: str) -> list[dict]:
                return underlying.drain_private(cid)

        transport = InterruptedReply()
        client._transport = transport
        arguments = dict(preset_id='preset-1', request_id='lost-accepted', device_id='edge', ip='edge',
            compute=dict(harness='external', model='fixture', source='owner', effort='high'))
        with self.assertRaises(OSError):
            flow.begin(**arguments)
        original = deepcopy(flow.hold)
        self.assertEqual(room.host.identity.grant_count, 1, 'first POST must actually admit before reply loss')
        self.assertFalse(client.can_answer)
        with self.assertRaisesRegex(arrival.ArrivalRefusal, 'request_conflict'):
            flow.begin(**dict(arguments, request_id='other'))
        self.assertEqual(len(transport.posts), 1)
        fixture.now += 1_000
        room.now = fixture.now
        with self.assertRaisesRegex(SnapRefusal, 'context_mismatch'):
            flow.begin(**arguments)
        self.assertEqual(transport.posts[1], transport.posts[0], 'retry replaced the accepted signed join bytes')
        self.assertFalse(client.can_answer, 'a valid signature with a wrong digest must not grant authority')
        with self.assertRaisesRegex(SnapRefusal, 'proof_required'):
            flow.begin(**arguments)
        self.assertFalse(client.can_answer, 'an invalid receipt signature must not grant authority')
        # Pending native admission also rejects changed arguments before wallet
        # proof or transport work, independently of the outer controller gate.
        pending = json.loads(transport.posts[0])
        def unexpected_proof(body: bytes) -> dict:
            raise AssertionError('retry changed the signed wallet proof')
        with self.assertRaisesRegex(SnapRefusal, 'request_conflict'):
            client.join(account_id=original['account_id'], nft_token_id=original['token_id'],
                persona_digest=original['persona_digest'], session_public_key=pending['session_public_key'],
                request_id=arguments['request_id'], declared_compute=dict(arguments['compute'], model='other'),
                prove_wallet=unexpected_proof)
        recovered = flow.begin(**arguments)
        self.assertEqual(recovered, original)
        self.assertTrue(client.can_answer)
        self.assertEqual(len(transport.posts), 4)
        self.assertTrue(all(body == transport.posts[0] for body in transport.posts))
        self.assertEqual((transport.manifest_calls, transport.challenge_calls), (1, 1))
        self.assertEqual(room.host.identity.grant_count, 1)
        self.assertEqual(len(room.arena.members), 1)
        self.assertEqual(fixture.service.counts(), dict(total=50, held=1, claimed=0, available=49))
        self.assertEqual(fixture.contract.claims, [])
        snapshot = client.member_snapshot(request_id='recovered-read')
        client.accept_terms(snapshot['terms']['version'], request_id='recovered-accept')
        self.assertEqual(client.authenticate(request_id='recovered-socket')['type'], 'control_ready')
        with self.assertRaisesRegex(arrival.ArrivalRefusal, 'request_conflict'):
            flow.begin(**arguments)
        self.assert_expired_pending_refuses()

    def assert_expired_pending_refuses(self) -> None:
        setup = ArrivalRecovery()
        setup.setUp()
        self.addCleanup(setup.doCleanups)
        flow, client, room = setup.real_client('/never-drop')
        underlying = client._transport
        posts = []

        class LostReply:
            def request(self, method: str, target: str, body: bytes = b'') -> dict:
                reply = underlying.request(method, target, body)
                if target == '/room/join':
                    posts.append(body)
                    raise OSError('synthetic accepted-response loss before challenge expiry')
                return reply

        client._transport = LostReply()
        arguments = dict(preset_id='preset-1', request_id='expired-pending', device_id='edge', ip='edge',
            compute=dict(harness='external', model='fixture', source='owner', effort='high'))
        with self.assertRaises(OSError):
            flow.begin(**arguments)
        original = deepcopy(flow.hold)
        setup.fixture.now += arrival.CHALLENGE_MS
        room.now = setup.fixture.now
        with self.assertRaisesRegex(SnapRefusal, 'proof_required'):
            flow.begin(**arguments)
        self.assertEqual(len(posts), 1, 'expired admission must refuse before replaying a POST')
        self.assertFalse(client.can_answer)
        self.assertEqual(flow.hold, original)
        self.assertEqual(setup.fixture.service.counts()['held'], 1)
        self.assertEqual(setup.fixture.contract.claims, [])


if __name__ == '__main__':
    unittest.main()
