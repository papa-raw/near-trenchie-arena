"""Synthetic local fixture for the new member case; never a deployed identity adapter."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from near.arena.snap_client import SnapClient
from near.arena.room_host import RoomHost
from near.members.runtime import MemberHandler, MemberSession
from room.slots import SlotStore
import server
import sim
import test_room_host as authority

NAMES = {'clover': 'Clover', 'pebble': 'Pebble', 'moss': 'Moss', 'house': 'House persona'}


class RoomBytes:
    def __init__(self, case: authority.CopiedRoom, token: str) -> None:
        self.case, self.token = case, token
        self.grant = None
        self.owner_requests = []
        self.hold = None
        self.hold_next = False
        self.drop_next = False
        self.read_delay_ms = 0

    def request(self, method: str, target: str, body: bytes = b'') -> dict:
        write = target in {'/room/owner/terms/accept','/room/owner/proposals/accept','/room/owner/proposals/decline'}
        if target.startswith('/room/owner/'):
            self.owner_requests.append(json.loads(body))
        if write and self.hold_next:
            self.hold_next = False
            if not self.hold.wait(timeout=10):
                raise OSError('synthetic member response held too long')
        reply = self.case.arena.control.request(method, target, body, ip=self.token)
        if target == '/room/owner/snapshot' and reply.get('type') == 'owner_response':
            self.case.now += self.read_delay_ms  # Genuine response bytes, delayed trusted receipt time.
        if write and self.drop_next:
            self.drop_next = False
            raise OSError('synthetic response lost after the room recorded it')
        return reply

    def open_control(self, url: str) -> dict:
        return self.case.arena.control.open_control(ip=self.token)

    def frame(self, connection_id: str, body: bytes) -> dict:
        return self.case.arena.control.frame(connection_id, body)

    def drain_private(self, connection_id: str) -> list[dict]:
        return self.case.arena.control.drain_private(connection_id)

    def self_bound(self) -> bool:
        keys = ('context','grant_id','session_key_id','member_id','nft_token_id','persona_digest','slot_id','generation','token')
        allowed = {'snapshot','accept_terms','accept_proposal','decline_proposal'}
        return all(request['action'] in allowed and all(request[key] == self.grant[key] for key in keys)
                   for request in self.owner_requests)


class MemberCases:
    """Create real services with synthetic reconciled terms, then use member routes."""

    def __init__(self, *, published: bool = True) -> None:
        self.session = None
        self.case = None
        self.transports = []
        self.reset(published=published)

    def reset(self, *, published: bool = True, proposal: bool = False, version: str = '7', accepted: bool = False) -> None:
        with self.session.lock if self.session else nullcontext():
            if self.case is not None:
                self.case.doCleanups()
            case = authority.CopiedRoom()
            case.setUp()
            self.case = case
            case.context['room_id'] = 'meadow-ring'
            case.now = int(datetime(2026,11,9,17,59,58,tzinfo=timezone.utc).timestamp()*1000)
            state = case.host.service.export_owner_state()
            state['context'] = deepcopy(case.context)
            state['terms']['version'] = version
            if not published:
                state['terms_published'] = False  # Explicit trusted source checkpoint, never a browser result.
            slots = SlotStore(Path(case.tmp.name)/'members-slots',case.context['room_id'],16,clock=lambda:case.now)
            case.host = RoomHost(slots,case.context,now_ms=lambda:case.now,sign=case.sign,
                verify_session=case.verify_session,key_id='room_key_a',proof_methods=('synthetic_v1',),
                consume_nonce=case.consume,security_event=case.commit_security,ready=lambda:case.ready,
                admission_open=lambda:case.admit,owner_state=state,
                owner_member_name=lambda binding:NAMES[binding['nft_token_id']])
            case.arena = server.Arena(case.context,[1,2,3,4,5],data_dir=Path(case.tmp.name)/'members-engine',
                room_factory=case.host,profile_provider=case.profile,identity_resolver=case.resolve,
                receipt_signer=case.host.sign_receipt,admission_gate=case.host.admission_ready,
                life_guard=case.host.life_guard,server_time_ms=lambda:case.now,
                pick_resolver=lambda binding,payload:sim.rules_dict(sim.DEFAULT_RULES['default_loadout']))
            self.clients = {token:self.join(token) for token in NAMES}
            self.clover = self.clients['clover']
            if accepted or proposal:
                self.clover.accept_terms(version,request_id='initial-terms')
            public = self.client(RoomBytes(case,'public'))
            if self.session is None:
                self.session = MemberSession(self.clover,connect=lambda:self.clover,
                    public_client=public,room_label='Meadow ring')
            else:
                self.session.client, self.session.public_client = self.clover, public
            if proposal:
                self.propose()

    def client(self, transport: RoomBytes) -> SnapClient:
        case = self.case
        return SnapClient(case.context,transport,now_ms=lambda:case.now,
            sign_session=lambda body:authority.encoded(hmac.digest(b'synthetic-session',body,'sha512')),
            verify_room=lambda key,body,signature:hmac.compare_digest(signature,case.sign(body)),
            trusted_key_ids=('room_key_a',))

    def join(self, token: str) -> SnapClient:
        case = self.case
        transport = RoomBytes(case,token)
        client = self.client(transport)
        grant = client.join(account_id=token+'.near',nft_token_id=token,
            persona_digest=hashlib.sha256(token.encode()).hexdigest(),session_public_key=case.example('SessionPublicKey'),
            request_id='join-'+token,declared_compute=dict(harness='external',model='fixture',source='owner',effort='high'),
            prove_wallet=lambda body:dict(method_id='synthetic_v1',key_id='wallet_a',
                proof_bytes=authority.encoded(hmac.digest(b'synthetic-wallet',body,'sha512'))))
        if grant.get('state') != 'accepted':
            raise AssertionError('synthetic member join refused')
        transport.grant = grant
        self.transports.append(transport)
        if token == 'clover':
            self.clover_transport = transport
        return client

    def propose(self) -> None:
        grants = [transport.grant for transport in self.transports if transport.case is self.case]
        self.case.host.service.propose_owner_change(proposal_id='interval-v8',proposed_ms='1500',
            boundary_segment_id='segment:1',expires_at=str(self.case.now+2000),
            required_members=[grant['member_id'] for grant in grants])
        for token in ('pebble','moss'):
            self.clients[token].answer_change('interval-v8','7',accept=True,request_id='initial-'+token)

    def control(self, request: dict) -> dict:
        action = request['action']
        if action == 'reset':
            self.reset(proposal=request.get('proposal',False),version=request.get('version','7'),accepted=request.get('accepted',False))
        elif action == 'unavailable':
            self.case.ready = False
        elif action == 'available':
            self.case.ready = True
        elif action == 'disconnect':
            self.session.client = None
        elif action == 'expire':
            self.case.now += 3000
        elif action == 'publish_terms':
            self.case.host.service.publish_owner_terms()
        elif action == 'accept_last':
            self.clients['house'].answer_change('interval-v8','7',accept=True,request_id='last-member')
        elif action == 'hold':
            self.clover_transport.hold = threading.Event()
            self.clover_transport.hold_next = True
        elif action == 'release':
            self.clover_transport.hold.set()
        elif action == 'drop':
            self.clover_transport.drop_next = True
        elif action == 'facts':
            requests = self.clover_transport.owner_requests
            return dict(write_count=sum(row['action'] in {'accept_terms','accept_proposal','decline_proposal'} for row in requests),
                self_bound=self.self_bound(),current_interval=self.case.host.service.export_owner_state()['terms']['input_interval_ms'])
        else:
            raise ValueError('unknown synthetic host control')
        return {'ok':True}

    def self_bound(self) -> bool:
        return all(transport.self_bound() for transport in self.transports)

    def close(self) -> None:
        for transport in self.transports:
            if transport.hold is not None:
                transport.hold.set()
        if self.case is not None:
            self.case.doCleanups()


def case_handler(host: MemberCases) -> type[MemberHandler]:
    """Trusted fixture controls exist only in this test handler, never the page runtime."""
    class FixtureHandler(MemberHandler):
        def do_POST(self) -> None:
            if self.path == '/__fixture' and self.headers.get('X-Fixture') == 'synthetic':
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 4096:
                    self.json_reply(400,{'error':'bad_message'})
                    return
                self.json_reply(200,host.control(json.loads(self.rfile.read(size))))
                return
            super().do_POST()
    return FixtureHandler
