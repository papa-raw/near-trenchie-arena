"""New sustained signed-read regression over the actual copied room."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'near/arena'), str(Path(__file__).resolve().parent)]
import member_fixture
from near.arena.snap_client import SnapRefusal, _MEMBER_READ_TTL_MS
from room.policy import canonical_bytes


class MemberSource(unittest.TestCase):
    def test_repeated_signed_reads_preserve_renewed_member_and_write_replay_guard(self) -> None:
        host = member_fixture.MemberCases()
        self.addCleanup(host.close)
        host.clover.authenticate(request_id='budget-control')
        for number in range(300):
            host.case.now += 10_000  # Six reads per minute, below the independent rate limit.
            renewed = host.clover.control('renew',{'lease_until':str(host.case.now+30_000)})
            self.assertEqual(renewed['state'],'accepted')
            try:
                value = host.session.read()
            except SnapRefusal as error:
                self.fail(f'fresh signed read {number+1} refused after a successful renewal: {error}')
            self.assertEqual(value['snapshot']['viewer_member_id'],host.clover_transport.grant['member_id'])
            self.assertFalse(value['snapshot']['terms']['accepted'])
        accepted = host.clover.accept_terms('7',request_id='consent-after-300-reads')
        self.assertTrue(accepted['terms']['accepted'])
        with self.assertRaisesRegex(SnapRefusal,'request_conflict'):
            host.clover.accept_terms('7',request_id='consent-after-300-reads')
        self.assertTrue(host.session.read()['snapshot']['terms']['accepted'])
        self.assertTrue(host.self_bound())
        print(json.dumps({'signed_reads':301,'renewals':300,'elapsed_ms':3_000_000,
                          'own_consent_after_reads':True,'write_replay_refused':True}))

    def test_signed_read_expiry_rejects_exact_replay_tampering_and_stale_request(self) -> None:
        host = member_fixture.MemberCases()
        self.addCleanup(host.close)
        self.assertIsNotNone(host.session.read()['snapshot']['terms'])
        request = deepcopy(host.clover_transport.owner_requests[-1])
        self.assertEqual(request['payload'],{'expires_at':str(host.case.now+_MEMBER_READ_TTL_MS)})

        def post(value: dict) -> dict:
            return host.clover_transport.request('POST','/room/owner/snapshot',canonical_bytes(value))

        self.assertEqual(post(request).get('code'),'request_conflict')
        altered = deepcopy(request)
        altered['payload']['expires_at'] = str(int(altered['payload']['expires_at'])-1)
        self.assertEqual(post(altered).get('code'),'proof_required',
                         'an in-window changed expiry still needs a fresh valid owner signature')
        host.case.now += 15_001  # Grant remains live; only this signed read has expired.
        self.assertEqual(post(request).get('code'),'proof_required')
        self.assertIsNotNone(host.session.read()['snapshot']['terms'])
        state = host.case.host.service.export_owner_state()
        self.assertFalse(any(row['request_id']==request['request_id'] for row in state['read_requests']))
        self.assertTrue(host.self_bound())
        print(json.dumps({'exact_read_replay_refused':True,'changed_expiry_signature_refused':True,
                          'expired_read_refused':True,'fresh_read_after_expiry':True}))

    def test_signed_read_reply_arriving_after_its_expiry_is_not_current(self) -> None:
        host = member_fixture.MemberCases()
        self.addCleanup(host.close)
        host.clover_transport.read_delay_ms = 15_001
        with self.assertRaisesRegex(SnapRefusal,'proof_required'):
            host.session.read()
        host.clover_transport.read_delay_ms = 0
        self.assertIsNotNone(host.session.read()['snapshot']['terms'])
        self.assertTrue(host.self_bound())
        print(json.dumps({'late_genuine_signed_reply_refused':True,'next_fresh_read_succeeds':True}))


    def test_a_member_read_from_a_client_clock_ahead_of_the_room_still_passes(self) -> None:
        # rejoin-red: the client's room clock adds the real time since its last reply, so between 50 ms ticks it runs
        # ahead of the room's. With no margin (expiry = client now + 15 000, the room's whole window) a client 1 ms
        # ahead was refused proof_required; LiveRejoin failed that way. Ahead by up to 999 ms must still read.
        host = member_fixture.MemberCases()
        self.addCleanup(host.close)
        for ahead in (1, 50, 999):
            host.clover._now_ms = lambda ahead=ahead: host.case.now + ahead
            snapshot = host.clover.member_snapshot(request_id=f'clock-ahead-{ahead}')
            self.assertIsNotNone(snapshot['terms'])
            request = host.clover_transport.owner_requests[-1]
            self.assertLessEqual(int(request['payload']['expires_at']), host.case.now + 15_000)
        print(json.dumps({'client_ahead_ms_read_ok':[1,50,999],'ttl_ms':_MEMBER_READ_TTL_MS}))


if __name__ == '__main__':
    unittest.main()
