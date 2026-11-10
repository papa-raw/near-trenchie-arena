"""New regression: signed public commands must retain their actual replayed life."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import test_room_host as fixture
from test_engine_evidence import drive
from portable_records import EngineRecords, _project
import replay
from room.ledger import digest


class RecordLifeBinding(unittest.TestCase):
    def test_cross_fighter_life_refuses_and_join_checkpoint_is_bound(self) -> None:
        case = fixture.CopiedRoom()
        case.setUp()
        self.addCleanup(case.doCleanups)
        clients, picks = [], []
        for token in ('alice','bob'):
            grant = case.join(token)
            cid, ready = case.authenticate(grant)
            picks.append(case.predict(grant,cid,ready))
            clients.append((grant,cid))
        drive(case,20,clients,[2,2])
        grant, cid = clients[0]
        intent = case.control(grant,'IntentRequest',picks[0]['life_id'],2)
        intent['payload'].update(fighter_id='alice',focus=None,avoid=None,loot='ignore',sig='hold',leave=False,say=None)
        receipt = case.arena.control.frame(cid,case.policy.canonical_bytes(case.signed(intent)))
        self.assertEqual(receipt['state'],'accepted')
        drive(case,1180,clients,[3,2])
        archive = case.arena.store.segment('segment:0')
        original = deepcopy(archive)
        valid, _ = _project(archive)
        self.assertEqual(archive,original)
        forged = deepcopy(archive)
        event = next(row for row in forged['sealed']['input_events'] if row['kind']=='intent')
        self.assertEqual(event['life_id'],picks[0]['life_id'])
        event['life_id'] = picks[1]['life_id']
        event['record_hash'] = digest({key:value for key,value in event.items() if key!='record_hash'})
        forged['sealed']['inputs_hash'] = digest(forged['sealed']['input_events'])
        forged['sealed']['sealed_result_hash'] = replay.engine_commitment(forged)
        self.assertEqual(forged['commands'],archive['commands'])
        self.assertEqual(forged['sealed']['lives'],archive['sealed']['lives'])
        self.assertEqual(forged['sealed']['final_state_hash'],archive['sealed']['final_state_hash'])

        class Archive:
            def segment(self, segment_id: str) -> dict:
                if segment_id != 'segment:0':
                    raise FileNotFoundError(segment_id)
                return deepcopy(forged)

        context = deepcopy(case.context)
        context['audience'] = 'near:mainnet:'+context['contract_ids']['arena']+':post_batch'
        records = EngineRecords(Archive(),Path(case.tmp.name)/'life-wire.sqlite',case.context,context,
            key_id='room_key_a',sign=case.sign,verify=lambda key,body,signature:signature==case.sign(body),
            key_allowed=lambda key:key=='room_key_a')
        case.host.service.records = records
        reply = case.arena.control.request('GET','/room/result?segment_id=segment:0',ip='spectator')
        self.assertEqual(reply.get('code'),'bad_message','cross-fighter life must not reach signing')
        self.assertNotIn('signature',reply)
        self.assertEqual(case.arena.store.segment('segment:0'),original)
        self.assertNotEqual(valid['inputs_hash'],forged['sealed']['inputs_hash'])

        audit = fixture.CopiedRoom()
        audit.setUp()
        self.addCleanup(audit.doCleanups)
        own = audit.join()
        own_cid, _ = audit.authenticate(own)
        fixture.assert_admission_audit(audit,own,own_cid)


if __name__ == '__main__':
    unittest.main()
