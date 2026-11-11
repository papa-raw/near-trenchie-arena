"""New cases for the game-owned signed battle extension."""
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]


@contextmanager
def joined_room(transport_factory=None):
    import snap
    import snap_local
    from near.house.guard import Guard
    with tempfile.TemporaryDirectory() as directory, patch.object(snap_local.secrets, 'randbelow', return_value=1):
        dev = snap_local.DevRoom(8765, directory)
        dev.feed.guard = Guard({'names':[], 'handles':[], 'slurs':['brambleword']}, [])
        def call(url, method='GET', body=None, headers=None, timeout=60, seen=None):
            parsed = urlsplit(url)
            target = parsed.path + ('?' + parsed.query if parsed.query else '')
            raw = json.dumps(body).encode() if isinstance(body, dict) else body or b''
            status, value = dev.route(method, target, raw, '127.0.0.1')
            if status != 200:
                raise ValueError('fixture HTTP ' + str(status))
            if seen is not None:
                seen.update(now=dev.round.vnow(), at=0, paused=True)
            return value
        args = types.SimpleNamespace(url='http://127.0.0.1:8765', name='critbee', preset='survivor', spread='40,30,20,10', zero=10)
        with patch.object(snap, 'call', side_effect=call):
            factory = {} if transport_factory is None else {'transport_factory':lambda base,who:transport_factory(dev,base,who)}
            keeper = snap.Keeper(args, **factory)
            keeper.start('1')
            dev.round.arena.advance(12)
            yield dev, keeper


class BattleHost(unittest.TestCase):
    def test_old_signed_result_path_replays_a_native_behaviour_input(self):
        with joined_room() as (dev, keeper):
            client, arena = keeper.client, dev.round.arena
            ack = client.control('behaviour',{'v':1,'stance':'flee'},life_id=keeper.life_id)['ack']
            self.assertEqual(ack['status'],'applied')
            arena.advance(12)
            self.assertEqual(client.control('leave',{'reason':'leave'},life_id=keeper.life_id)['state'],'accepted')
            arena.advance(1201-arena.sim.state['tick'])
            result = client.result('segment:0')
            self.assertTrue(result['completed'])
            self.assertTrue(any(life['nft_token_id']==keeper.token for life in result['lives']))
            native = arena.store.segment('segment:0')
            self.assertTrue(any(row['kind']=='input' and row['value']['kind']=='behaviour' for row in native['commands']))
            self.assertFalse(any(row['kind']=='behaviour' for row in native['sealed']['input_events']))
            # A fixture archival argument set exercises the production read path;
            # the replay itself is real and reads the complete native journal.
            from near.chain import archival, batch
            import server
            sealed = native['sealed']
            segment = {key:sealed[key] for key in batch.SEGMENT_HASHES}
            segment.update(segment_id='battle-segment-0',commit_id='0',seed_index=0,kos=batch.segment_kos(sealed))
            fight_hash = batch.fight_hash([segment])
            local = Path(dev.data_dir)/'battle-native.json'
            local.write_text(json.dumps(native))
            read = dict(tx='fixture',rpc='https://archival.invalid',signer='fixture.testnet',receiver='arena.testnet',
                        method='post_batch',args=dict(batch_id='fixture-batch',segments=[segment],rows=[]),
                        outcome={'events':[{'event':'post_batch','data':[{'fight_hash':fight_hash}]},
                                           {'event':'apply_result','data':[{'status':'applied'}]}]})
            state = {'batches':[{'batch_id':'fixture-batch','fight_hash':fight_hash,'local':[str(local)]}]}
            with patch.object(server,'replay_segment',wraps=server.replay_segment) as replay:
                report, ok = archival.check(read,state,replay=1)
            self.assertTrue(ok,report)
            replay.assert_called_once()
            self.assertEqual(replay.call_args.args[0]['commands'],native['commands'])
            self.assertTrue(any(row['ok'] and 'replay final state' in row['check'] for row in report['checks']))

    def test_invalid_behaviour_types_get_a_refusal_without_fencing_the_host(self):
        with joined_room() as (dev, keeper):
            for wrong in ('loud',None,[],{},True):
                reply = keeper.client.control('behaviour',{'v':1,'drives':{'protect':wrong}},life_id=keeper.life_id)['ack']
                self.assertEqual(reply['status'],'refused')
                self.assertTrue(reply['refused'] and all(row['fix'] for row in reply['refused']))
                self.assertFalse(dev.round.host.service._failed)
            valid = keeper.client.control('behaviour',{'v':1,'stance':'flee'},life_id=keeper.life_id)['ack']
            self.assertEqual(valid['status'],'applied')

    def test_live_critbee_plan_and_caps_persist_through_three_respawns(self):
        import snap
        import time
        from battle_live_host import LivePeer
        from battle_transport import LiveTransport
        from snap_live import LiveSession
        peers = []
        def factory(dev, base, who):
            class PeerSocket:
                def __init__(self, url):
                    self.queue = []
                    self.peer = LivePeer(dev, self.queue.append, ip='127.0.0.1')
                    peers.append(self.peer)
                def send(self, value): self.peer.receive(value)
                def receive(self, timeout): return self.queue.pop(0) if self.queue else None
                def close(self): self.peer.close()
            return LiveTransport(snap.Transport(base,who),connector=PeerSocket)
        with joined_room(factory) as (dev, keeper):
            plan = {'v':1,'stance':'flee','gate':{'never':True},
                    'reflexes':[{'if':{'always':True},'then':{'say':'AAAA RUN','repeat':True}}]}
            output = []
            session = LiveSession(keeper, output.append)
            session.command(json.dumps(plan))
            ack = output[-1]['receipt']['ack']
            self.assertEqual(output[-1]['summary'],ack['summary'])
            self.assertEqual(ack['status'],'applied',ack)
            normalised, starts, attacks, latencies = ack['behaviour'], set(), [], []
            confirmed = False
            arena = dev.round.arena
            for _ in range(8000):
                arena.advance()
                ready = time.monotonic()
                peers[0].publish()
                first_event = len(output)
                session.beat()
                for event in output[first_event:]:
                    latencies.append(time.monotonic()-ready)
                    self.assertEqual(event['tick'],arena.sim.state['tick'])
                    if event['kind']=='behaviour': confirmed = True
                    if event['kind']=='life_start': starts.add(event['life_id'])
                    if event['kind'] in ('attack','signature') and event.get('fighter_id')==keeper.token: attacks.append(event)
                fighter = arena.sim.state['fighters'][keeper.token]
                if confirmed:
                    self.assertEqual(fighter['behaviour'],normalised)
                    if fighter['state']=='alive': self.assertIsNone(fighter['target'])
                if len(starts)>=4: break
            self.assertEqual(len(peers),1,'three respawns use the same live connection')
            self.assertTrue(confirmed,'the apply event confirms the signed receipt')
            self.assertGreaterEqual(len(starts),4,'four lives include three genuine respawns')
            self.assertEqual(attacks,[],'critbee swings at nobody')
            lines = [row for row in dev.feed.rows if row['who']==keeper.token]
            self.assertGreaterEqual(len(lines),4)
            self.assertTrue(all(row['text']=='AAAA RUN' for row in lines))
            self.assertTrue(all(b['tick']-a['tick']>=200 for a,b in zip(lines,lines[1:])))
            self.assertTrue(latencies and max(latencies)<0.2,'tick events publish within0.2s in-process; the network is checked in review')
    def test_signed_behaviour_clipping_replay_and_legacy_order_clock(self):
        import snap
        from room.policy import canonical_bytes
        with joined_room() as (dev, keeper):
            arena, client = dev.round.arena, keeper.client
            self.assertEqual(int(client.manifest()['limits']['intent_interval_ms']), 500)
            payload = {'v':1, 'drives':{'keep_away':40,'keep_away_radius':40}, 'gate':{'distance_under':1}}
            captured = []
            original = keeper.transport.frame
            def capture(cid, body):
                captured.append(body)
                return original(cid, body)
            keeper.transport.frame = capture
            reply = client.control('behaviour', payload, life_id=keeper.life_id)
            self.assertEqual(reply['ack']['status'],'clipped')
            self.assertEqual(reply['ack']['behaviour']['drives']['keep_away'],10)
            self.assertEqual(reply['ack']['behaviour']['drives']['keep_away_radius'],12)
            self.assertIn('persists across respawns',reply['ack']['summary'])
            count = arena.sequence
            again = original(client._connection,captured[-1])
            self.assertEqual(again,reply); self.assertEqual(arena.sequence,count)
            changed = json.loads(captured[-1]); changed['payload']={'v':1,'stance':'berserk'}
            changed['signature']=snap.encoded(keeper.key.sign(canonical_bytes(changed,exclude=('signature',))))
            self.assertEqual(original(client._connection,canonical_bytes(changed))['code'],'request_conflict')
            order = dict(fighter_id=keeper.token,focus=None,avoid=None,loot='ignore',sig='hold',leave=False,say=None)
            old = client.control('intent',order,life_id=keeper.life_id)
            self.assertEqual(old['state'],'refused'); self.assertEqual(old['code'],'rate_limited')
            arena.advance(10)
            self.assertEqual(client.control('intent',order,life_id=keeper.life_id)['state'],'accepted')
            refused = client.control('behaviour',{'v':1,'stance':'loot'},life_id=keeper.life_id)['ack']
            self.assertEqual(refused['status'],'refused')
            self.assertTrue(any('0.5 s' in row['fix'] for row in refused['refused']))
            bad = json.loads(captured[-1]); bad['sequence']='99'; bad['signature']='A'*86
            self.assertEqual(original(client._connection,canonical_bytes(bad))['code'],'proof_required')
            self.assertFalse(dev.round.host.service._failed)

    def test_speech_guard_emoji_and_shared_ten_second_cap(self):
        with joined_room() as (dev, keeper):
            self.assertEqual(dev.feed.rate,200)
            client = keeper.client
            posted = client.control('speech',{'text':'KEEP AWAY!', 'emoji':None},life_id=keeper.life_id)['ack']
            self.assertEqual(posted['status'],'posted')
            self.assertTrue(posted['speech']['emoji_fallback'])
            old = client.control('intent',dict(fighter_id=keeper.token,focus=None,avoid=None,loot='ignore',sig='hold',
                                 leave=False,say='STILL HERE!'),life_id=keeper.life_id)
            self.assertEqual(old['state'],'accepted')
            self.assertEqual(dev.speech_results[keeper.token]['sequence'],old['sequence'])
            self.assertEqual(dev.speech_results[keeper.token]['speech']['refused'],'rate_limited')
            refused = client.control('speech',{'text':'KEEP AWAY!', 'emoji':None},life_id=keeper.life_id)['ack']
            self.assertEqual(refused['status'],'refused')
            self.assertIn('10',refused['summary']); self.assertIn('wait',refused['summary'].lower())
            dev.round.arena.advance(200)
            # Refresh the keeper's life notice after any genuine KO in these ticks.
            keeper.tick()
            blocked = client.control('speech',{'text':'brambleword', 'emoji':'free text'},life_id=keeper.life_id)['ack']
            self.assertEqual(blocked['status'],'blocked')
            self.assertNotIn('brambleword',json.dumps(dev.feed.public()))
            self.assertTrue(blocked['speech']['emoji_fallback'])

    def test_reflex_speech_is_guarded_before_it_enters_the_replay_log(self):
        with joined_room() as (dev, keeper):
            plan = {'v':1,'reflexes':[{'if':{'self_hp_above_pct':1},'then':{'say':'brambleword'}}]}
            reply = keeper.client.control('behaviour',plan,life_id=keeper.life_id)['ack']
            self.assertEqual(reply['status'],'clipped')
            self.assertNotIn('brambleword',json.dumps(reply))
            self.assertIn('speech',reply['summary'])
            dev.round.arena.advance(3)
            self.assertNotIn('brambleword',json.dumps(dev.round.arena.commands))
            rows = [row for row in dev.feed.rows if row['who']==keeper.token]
            self.assertTrue(rows, 'the reflex reaches the shared guarded feed')
            self.assertIn('blocked line',rows[-1]['text'],'a guarded reflex emote stays labelled')


class BattleEnvelope(unittest.TestCase):
    def test_client_checks_the_battle_signature_and_every_request_binding(self):
        import json
        import snap
        from snap_client import SnapClient, SnapRefusal
        from battle_protocol import BINDING
        from room.policy import canonical_bytes, digest
        from snap_local import make_contexts
        context, _ = make_contexts(8765, 0)
        binding = dict(context=context, grant_id='grant-a', session_key_id='session-a', member_id='member-a',
                       nft_token_id='dev-bee', persona_digest='a'*64, slot_id='slot-a', generation='1')
        room_key, owner_key = snap.Ed25519PrivateKey.generate(), snap.Ed25519PrivateKey.generate()
        public = snap.encoded(room_key.public_key().public_bytes(snap.serialization.Encoding.Raw, snap.serialization.PublicFormat.Raw))
        for changed in ({}, {'request_digest':'b'*64}, {'generation':'2'}, {'life_id':'other-life'}, {'signature':'A'*86}):
            class Transport:
                def frame(self, connection_id, raw):
                    request = json.loads(raw)
                    self.request = request
                    self.reply = {key: deepcopy(request[key]) for key in BINDING}
                    ack = dict(type='behaviour_ack', v=1, fighter='dev-bee', seq=1, status='applied', receive_tick=10,
                               apply_tick=12, applies_in_ms=100, behaviour={'v':1}, clipped=[], refused=[], notes=[],
                               summary='New behaviour recorded', rules_hash=context['rules_hash'])
                    self.reply.update(domain='arena.battle.receipt.v1', type='battle_receipt', kind=request['kind'],
                                      sequence=request['sequence'], life_id=request['life_id'],
                                      request_digest=digest(request, exclude=('signature',)), ack=ack, key_id='room-key')
                    self.reply.update(changed)
                    if 'signature' not in changed:
                        self.reply['signature'] = snap.encoded(room_key.sign(canonical_bytes(self.reply, exclude=('signature',))))
                    return self.reply
            transport = Transport()
            client = SnapClient(context, transport, now_ms=lambda:1000,
                                sign_session=lambda raw:snap.encoded(owner_key.sign(raw)),
                                verify_room=lambda key,raw,sig:snap.verify_ed25519(public,raw,sig), trusted_key_ids=('room-key',))
            # This unit case starts after the room's separately tested authentication.
            client._grant = deepcopy(binding); client._connection = 'c1'
            if changed:
                with self.subTest(changed=changed), self.assertRaises((SnapRefusal, ValueError)):
                    client.control('behaviour', {'v':1,'stance':'flee'}, life_id='dev-bee:life:1')
            else:
                reply = client.control('behaviour', {'v':1,'stance':'flee'}, life_id='dev-bee:life:1')
                self.assertEqual(reply['ack']['summary'], 'New behaviour recorded')
                self.assertEqual(transport.request['domain'], 'arena.battle.v1')
                self.assertEqual(client._sequence, 2)

    def test_closed_envelopes_reject_binding_sequence_and_receipt_substitution(self):
        from battle_protocol import check_request, check_receipt
        from room.policy import BoundaryError, digest
        from snap_local import make_contexts
        context, _ = make_contexts(8765, 0)
        request = dict(context=context, grant_id='grant-a', session_key_id='session-a', member_id='member-a',
                       nft_token_id='dev-bee', persona_digest='a' * 64, slot_id='slot-a', generation='1',
                       domain='arena.battle.v1', kind='behaviour', sequence='4', life_id='dev-bee:life:1',
                       payload={'v': 1, 'stance': 'flee'}, signature='A' * 86)
        check_request(request)
        for changed in (dict(sequence='04'), dict(generation=1), dict(domain='room.control.v1'),
                        dict(extra='authority'), dict(signature='bad')):
            with self.subTest(changed=changed), self.assertRaises(BoundaryError):
                check_request(dict(request, **changed))
        ack = dict(type='behaviour_ack', v=1, fighter='dev-bee', seq=4, status='applied', receive_tick=10,
                   apply_tick=12, applies_in_ms=100, behaviour={'v':1}, clipped=[], refused=[], notes=[],
                   summary='New behaviour recorded', rules_hash=context['rules_hash'])
        receipt = {key: deepcopy(request[key]) for key in ('context','grant_id','session_key_id','member_id','nft_token_id','persona_digest','slot_id','generation')}
        receipt.update(domain='arena.battle.receipt.v1', type='battle_receipt', kind='behaviour', sequence='4',
                       life_id=request['life_id'], request_digest=digest(request, exclude=('signature',)),
                       ack=ack, key_id='room_key_a', signature='A' * 86)
        check_receipt(receipt)
        for key, value in (('fighter','dev-other'), ('seq',5), ('rules_hash','b'*64), ('apply_tick',None)):
            changed = deepcopy(receipt); changed['ack'][key] = value
            with self.subTest(ack_key=key), self.assertRaises(BoundaryError):
                check_receipt(changed)
        changed = deepcopy(receipt); changed['ack']['debug'] = 'unprojected'
        with self.assertRaises(BoundaryError): check_receipt(changed)


if __name__ == '__main__':
    unittest.main()
