"""New real-replay regression for duplicated joins and life starts."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import portable_records as port
import replay
import test_record_reuse as fixtures
import test_room_host as room_fixture
from room.ledger import digest


class RecordApplications(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Shared setup builds a fresh actual1200-tick archive; no test method runs.
        fixtures.RecordReuse.setUpClass.__func__(cls)

    def test_join_and_spawn_cannot_publish_one_application_twice(self) -> None:
        for kind, public_kind in (('join','join'), ('spawn','life_start')):
            with self.subTest(command=kind):
                case = room_fixture.CopiedRoom()
                case.setUp()
                self.addCleanup(case.doCleanups)
                signer = Mock(wraps=case.sign)
                context = deepcopy(case.context)
                context['audience'] = 'near:mainnet:'+context['contract_ids']['arena']+':post_batch'

                def read(native: dict, label: str) -> tuple[dict, port.EngineRecords]:
                    records = port.EngineRecords(fixtures.MutableArchive(native),
                        Path(case.tmp.name)/(label+'.sqlite'),case.context,context,
                        key_id='room_key_a',sign=signer,
                        verify=lambda key,body,signature:signature==case.sign(body),
                        key_allowed=lambda key:key=='room_key_a')
                    case.host.service.records = records
                    reply = case.arena.control.request('GET','/room/result?segment_id=segment:0',ip='spectator')
                    return reply, records

                intact, records = read(self.native,'intact')
                records.authority.verify_result(intact)
                self.assertEqual(signer.call_count,1)
                forged = deepcopy(self.native)
                index = next(i for i,row in enumerate(forged['commands']) if row['kind']=='input'
                             and row['value']['kind']==kind and row['value']['fighter_id']=='alice')
                command = deepcopy(forged['commands'][index])
                forged['commands'].insert(index+1,command)
                event = deepcopy(next(row for row in forged['sealed']['input_events']
                                      if row['kind']==public_kind and row['fighter_id']=='alice'))
                event['index'] = str(len(forged['sealed']['input_events']))
                event['record_hash'] = digest({key:value for key,value in event.items() if key!='record_hash'})
                forged['sealed']['input_events'].append(event)
                forged['sealed']['inputs_hash'] = digest(forged['sealed']['input_events'])
                forged['sealed']['sealed_result_hash'] = replay.engine_commitment(forged)
                actual = []
                game = replay.replay_segment(forged,input_sink=lambda sim,row:actual.append(deepcopy(row)))
                self.assertEqual(sum(row==command['value'] for row in actual),1)
                self.assertEqual(sum(row['kind']==public_kind and row['fighter_id']=='alice'
                                     and row['life_id']==event['life_id'] for row in forged['sealed']['input_events']),2)
                self.assertEqual(game.state_hash(),self.native['sealed']['final_state_hash'])
                facts = port.replay_evidence(forged)
                self.assertEqual(facts['lives'],self.native['sealed']['lives'])
                signer.reset_mock()
                rejected, forged_records = read(forged,'duplicate')
                self.assertEqual(rejected.get('code'),'bad_message',
                                 'one actual '+kind+' application must not publish two public rows')
                self.assertNotIn('signature',rejected)
                self.assertEqual(signer.call_count,0)
                self.assertEqual(forged_records.archive.value,forged,'refusal must preserve source bytes and locks')


if __name__ == '__main__':
    unittest.main()
