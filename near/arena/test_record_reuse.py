"""New cases for one-application evidence and native projection reuse."""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import test_room_host as fixture
from test_engine_evidence import drive
import portable_records as port
import replay
from room.ledger import Refusal, digest, sealed_hash


class MutableArchive:
    def __init__(self, value: dict) -> None:
        self.value = deepcopy(value)

    def segment(self, segment_id: str) -> dict:
        if segment_id != 'segment:0':
            raise FileNotFoundError(segment_id)
        return deepcopy(self.value)


class RecordReuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        case = fixture.CopiedRoom()
        case.setUp()
        cls.addClassCleanup(case.doCleanups)
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
        if receipt.get('state') != 'accepted':
            raise AssertionError('new fixture intent refused')
        drive(case,1180,clients,[3,2])
        cls.native = case.arena.store.segment('segment:0')

    def setUp(self) -> None:
        self.case = fixture.CopiedRoom()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.archive = MutableArchive(self.native)
        self.allowed = True
        self.sign = Mock(wraps=self.case.sign)
        context = deepcopy(self.case.context)
        context['audience'] = 'near:mainnet:'+context['contract_ids']['arena']+':post_batch'
        self.records = port.EngineRecords(self.archive,Path(self.case.tmp.name)/'reuse-wire.sqlite',
            self.case.context,context,key_id='room_key_a',sign=self.sign,
            verify=lambda key,body,signature:signature==self.case.sign(body),
            key_allowed=lambda key:self.allowed and key=='room_key_a')
        self.case.host.service.records = self.records

    def read(self) -> dict:
        return self.case.arena.control.request('GET','/room/result?segment_id=segment:0',ip='spectator')

    def test_duplicate_enqueue_cannot_publish_one_application_twice(self) -> None:
        forged = deepcopy(self.native)
        index = next(i for i,row in enumerate(forged['commands'])
                     if row['kind']=='input' and row['value']['kind']=='intent')
        forged['commands'].insert(index+1,deepcopy(forged['commands'][index]))
        event = deepcopy(next(row for row in forged['sealed']['input_events'] if row['kind']=='intent'))
        event['index'] = str(len(forged['sealed']['input_events']))
        event['record_hash'] = digest({key:value for key,value in event.items() if key!='record_hash'})
        forged['sealed']['input_events'].append(event)
        forged['sealed']['inputs_hash'] = digest(forged['sealed']['input_events'])
        forged['sealed']['sealed_result_hash'] = replay.engine_commitment(forged)
        facts = port.replay_evidence(forged)
        self.assertEqual(sum(row['kind']=='intent' for row in facts['input_lives']),1)
        self.assertEqual(sum(row['kind']=='intent' for row in forged['sealed']['input_events']),2)
        self.assertEqual(facts['final_state_hash'],self.native['sealed']['final_state_hash'])
        self.assertEqual(facts['lives'],self.native['sealed']['lives'])
        self.archive.value = forged
        result = self.read()
        self.assertEqual(result.get('code'),'bad_message','one actual application cannot become two signed rows')
        self.assertNotIn('signature',result)
        self.assertEqual(self.sign.call_count,0)
        self.assertEqual(self.archive.value,forged)

    def test_identical_reads_reuse_native_replay_but_recheck_source_key_and_seal(self) -> None:
        with patch.object(port,'replay_evidence',wraps=port.replay_evidence) as native_replay:
            first = self.read()
            self.records.authority.verify_result(first)
            first_count = native_replay.call_count
            second = self.read()
            self.records.authority.verify_result(second)
            second_count = native_replay.call_count-first_count
            self.assertEqual((first_count,second_count),(1,0))
            self.assertEqual(first,second)
            self.assertEqual(self.sign.call_count,2,'cached facts still require current signing authority')
            self.allowed = False
            denied = self.read()
            self.assertEqual(denied.get('code'),'proof_required')
            self.assertNotIn('signature',denied)
            self.assertEqual(self.sign.call_count,2)
            self.assertEqual(native_replay.call_count,first_count)
            self.allowed = True
            self.records.authority.verify_result(self.read())
            self.assertEqual(self.sign.call_count,3)
            # Same native seal hash, changed source commands: never a source-cache hit.
            damaged = deepcopy(self.native)
            damaged['commands'].append({'kind':'advance','value':0})
            self.assertEqual(damaged['sealed']['sealed_result_hash'],self.native['sealed']['sealed_result_hash'])
            self.archive.value = damaged
            with self.assertRaises((Refusal,ValueError)):
                self.records.result('segment:0')
            self.assertEqual(self.sign.call_count,3)
            self.assertEqual(native_replay.call_count,first_count+1)
            self.archive.value = deepcopy(self.native)
            # A changed portable ledger record must be checked even with a warm native cache.
            altered = self.records.ledger.sealed('segment:0')
            altered['lives'][0]['ko_count'] = '999'
            altered['sealed_result_hash'] = sealed_hash(altered)
            with patch.object(self.records.ledger,'sealed',return_value=altered):
                with self.assertRaisesRegex(Refusal,'bad_message'):
                    self.records.result('segment:0')
            self.assertEqual(self.sign.call_count,3)
            recovered = self.read()
            self.records.authority.verify_result(recovered)
            self.assertEqual(recovered,first)
            self.assertEqual(self.sign.call_count,4)
            self.assertEqual(self.archive.value,self.native)

    def test_overlapping_first_read_refuses_duplicate_verification(self) -> None:
        entered, release = threading.Event(), threading.Event()
        actual_replay = port.replay_evidence
        calls = []

        def held_replay(record: dict) -> dict:
            calls.append(record['sealed']['segment_id'])
            if len(calls) == 1:
                entered.set()
                if not release.wait(timeout=10):
                    raise AssertionError('first native verification was not released')
            return actual_replay(record)

        with patch.object(port,'replay_evidence',side_effect=held_replay):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(self.read)
                try:
                    self.assertTrue(entered.wait(timeout=5),'first read never reached native verification')
                    second = self.read()
                    self.assertEqual(second.get('code'),'rate_limited')
                    self.assertEqual(self.sign.call_count,0)
                finally:
                    release.set()
                first = pending.result(timeout=15)
            self.records.authority.verify_result(first)
            self.assertEqual(len(calls),1)
            self.records.authority.verify_result(self.read())
            self.assertEqual(len(calls),1,'completed verification must be reusable after contention')


if __name__ == '__main__':
    unittest.main()
