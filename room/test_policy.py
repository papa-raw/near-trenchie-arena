"""Focused guest and privacy boundaries over portable wire examples."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from room.policy import (BoundaryError, GuestPolicy, member_view, public_projection,
                         safe_error, validate)

_DEFS = json.loads(Path(__file__).with_name('protocol.schema.json').read_text())['$defs']


def example(name):
    return deepcopy(_DEFS[name]['examples'][0])


class PolicyCases(unittest.TestCase):
    def setUp(self):
        self.clock = [1900000000000]
        self.policy = GuestPolicy(now_ms=lambda: self.clock[0])
        self.binding = example('SlotBinding')
        self.capabilities = ('observe', 'intent', 'prediction', 'renew', 'leave')
        self.canary = 'PRIVATE_' + 'a91eb7c'

    def authorize(self, request, capabilities=None):
        return self.policy.authorize(self.binding, request,
                                     capabilities=self.capabilities if capabilities is None else capabilities,
                                     fighter_id='fighter_a', life_id='life_a')

    def refused(self, operation, code=None):
        with self.assertRaises(BoundaryError) as caught:
            operation()
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertNotIn(self.canary, json.dumps(caught.exception.error()))

    def test_guest_envelope(self):
        own = example('IntentRequest')
        self.authorize(own)
        self.clock[0] += 2000
        for verb in ('spawn', 'rule_change', 'house_balance', 'result', 'ban', 'execute'):
            request = deepcopy(own)
            request['kind'] = verb
            self.refused(lambda: self.authorize(request))
        request = deepcopy(own)
        request['payload']['fighter_id'] = 'fighter_b'
        self.refused(lambda: self.authorize(request), 'stale_slot')
        request = deepcopy(own)
        request['payload']['shell'] = self.canary
        self.refused(lambda: self.authorize(request), 'bad_message')
        self.refused(lambda: self.authorize(own, capabilities=('observe',)), 'proof_required')
        self.refused(lambda: self.authorize(own, capabilities=()), 'proof_required')
        own['payload']['say'] = None
        self.authorize(own, capabilities=('intent', 'spawn'))

    def test_guest_limits_survive_generation_rotation(self):
        # No banter: every refusal here must come from the two-second intent guard.
        request = example('IntentRequest')
        request['payload']['say'] = None
        self.authorize(request)
        self.refused(lambda: self.authorize(request), 'rate_limited')
        self.clock[0] += 1999
        self.refused(lambda: self.authorize(request), 'rate_limited')
        self.clock[0] += 1
        self.authorize(request)
        self.binding['generation'] = request['generation'] = '3'
        self.refused(lambda: self.authorize(request), 'rate_limited')
        self.clock[0] += 1999
        self.refused(lambda: self.authorize(request), 'rate_limited')
        self.clock[0] += 1
        self.authorize(request)

        # A separate history exercises the longer banter limit and payload bounds.
        self.policy = GuestPolicy(now_ms=lambda: self.clock[0])
        self.binding = example('SlotBinding')
        request = example('IntentRequest')
        self.authorize(request)
        self.refused(lambda: self.authorize(request), 'rate_limited')
        self.clock[0] += 1999
        self.refused(lambda: self.authorize(request), 'rate_limited')
        self.clock[0] += 1
        request['payload']['say'] = None
        self.authorize(request)
        self.clock[0] += 2000
        self.binding['generation'] = request['generation'] = '3'
        request['payload']['say'] = 'again'
        self.refused(lambda: self.authorize(request), 'rate_limited')
        request['payload']['say'] = None
        self.authorize(request)
        request['payload']['say'] = 'x' * 17000
        self.refused(lambda: self.authorize(request))
        request = example('IntentRequest')
        request['payload']['unknown'] = [[[[]]]] * 257
        self.refused(lambda: self.authorize(request))

    def test_owner_canary_wall(self):
        for name in ('PublicSnapshot', 'LedgerPage', 'ReplayPage', 'Clock', 'Limits', 'Manifest'):
            with self.subTest(name=name):
                raw = example(name)
                raw['private'] = {'prompt': self.canary, 'api_key': self.canary}
                if name == 'PublicSnapshot':
                    raw['fighters'][0]['reasoning'] = self.canary
                    raw['fighters'][0]['equipped'][0]['private'] = self.canary
                    raw['fighters'][0]['house_spend_microusd'] = '123'
                if name == 'ReplayPage':
                    for event in raw['input_events']:
                        event['private'] = self.canary
                        event['payload']['private'] = self.canary
                projected = public_projection(name, raw)
                validate(name, projected)
                self.assertNotIn(self.canary, json.dumps(projected))
                self.assertEqual(projected, public_projection(name, raw))
                if name == 'PublicSnapshot':
                    self.assertIsNone(projected['fighters'][0]['house_spend_microusd'])
                    self.assertEqual(projected['projectiles'], example(name)['projectiles'])
                    self.assertEqual(projected['telegraphs'], example(name)['telegraphs'])
                    self.assertEqual(projected['actions'], example(name)['actions'])
        raw = {'prompt': self.canary, 'api_key': self.canary, 'connection_status': 'connected',
               'receipts': [example('Receipt')], 'grant': example('JoinAccepted'),
               'player_spend_microusd': '123'}
        raw['receipts'][0]['private'] = self.canary
        raw['grant']['private'] = self.canary
        own = member_view('member_a', 'member_a', raw)
        self.assertEqual(len(own['receipts']), 1)
        self.assertEqual(own['grant']['token'], raw['grant']['token'])
        for viewer in ('member_b', None):
            self.assertEqual(member_view(viewer, 'member_a', raw), {})
        self.assertNotIn(self.canary, json.dumps(own))
        self.assertNotIn(self.canary, json.dumps(safe_error(self.canary)))
        self.refused(lambda: public_projection('JoinAccepted', raw), 'bad_message')

    def test_stands_wall_and_no_raw_status_fallback(self):
        self.refused(lambda: self.policy.authorize(None, example('IntentRequest'), capabilities=self.capabilities))
        snapshot = example('PublicSnapshot')
        snapshot['fighters'][0]['house'] = True
        snapshot['fighters'][0]['house_spend_microusd'] = '123'
        self.assertEqual(public_projection('PublicSnapshot', snapshot)['fighters'][0]['house_spend_microusd'], '123')
        snapshot['projection_version'] = 2
        self.refused(lambda: public_projection('PublicSnapshot', snapshot))
        self.refused(lambda: public_projection('operator', {'secrets': self.canary}))
        self.refused(lambda: member_view('member_a', 'member_a', {'connection_status': self.canary}))


if __name__ == '__main__':
    unittest.main()
