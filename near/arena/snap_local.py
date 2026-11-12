"""Local snap-in host (DEV): the room, the engine and the spectator socket in one process.

Run:  python3 -B near/arena/snap_local.py [--port 8765]

One loopback port serves three things from the same running arena:
  * the spectator WebSocket the first-look page draws (identical frames to dev_brawl.py),
  * the room's HTTP routes (`/room`, `/room/challenge`, `/room/join`, `/room/observe`, ...), plus a
    local shim for the control socket (`/room/control/open|frame|private`) so a plain HTTP client can
    drive it, and
  * `/dev/*`: DEV identity issue, terms, players, clock.

DEV means what it says. There is no wallet, no chain and no NFT. A joiner generates its own Ed25519 session
key and registers only the public half; the room signs with its own Ed25519 key and a joiner receives only the
room's public key, so a joiner can neither forge a room signature nor read another joiner's key. The copied room
protocol defines only a mainnet context, so its `network_id` field must read "mainnet"; the contract ids are
`dev-nft.local` and `dev-arena.local`, which exist on no chain, and the deployment id is `dev-local-r<round>`.
Every DEV trenchie is `dev-<name>` in the feed, in `/dev/players` and on its card. Loopback only: the host
refuses any Host header but its own, takes POSTs only as application/json, and allows cross-origin reads of
`/dev/players` and `/dev/health` from the first-look page's origin alone. Never expose this port directly.

Hosted (`--public-origin https://<name>`, run by `make play` behind nginx, inside a capped container): the same DEV
arena, with three differences. The public name joins the Host and Origin checks; the client address is nginx's
X-Real-IP, so the room's per-address limits see each visitor; and /dev/shutdown does not exist (404), with no admin
token printed. nginx stays in front: it terminates TLS, rate-limits and times out the public sockets, and refuses
the admin route too. It is still DEV: no wallet, chain or NFT.

One round: a join with no DEV trenchie present starts a fresh arena, so the joiner's life falls inside
segment:0; a join while another DEV trenchie keeps the round going lands in a later segment, and the result
reader signs every sealed segment for the lives locked, started and ended inside it. The round's results stay
readable until the next round starts. The 14 house trenchies fill the ring (six at most) and yield seats at their life boundaries.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import hashlib
import hmac
import inspect
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
import shlex
import shutil
import sys
import tempfile
import time
import traceback
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(HERE)]
import battle_protocol  # noqa: E402
import codec  # noqa: E402
import dev_brawl  # noqa: E402
import predict  # noqa: E402
import presets as battle_options  # noqa: E402
from dev_persona import check_sheet, sheet_digest, check_look, check_display_name  # noqa: E402
from near.house.feed import PublicFeed  # noqa: E402
from near.house.guard import Guard  # noqa: E402
from spectator_styles import SpectatorStyles  # noqa: E402
import server  # noqa: E402
import sim  # noqa: E402
from portable_records import EngineRecords  # noqa: E402
from cryptography.exceptions import InvalidSignature  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey  # noqa: E402
from room.policy import canonical_bytes  # noqa: E402
from room.slots import SlotStore  # noqa: E402
from room_host import RoomHost  # noqa: E402
from battle_live_host import serve_live  # noqa: E402
# --- house hook (near/house): the shared public feed and the live house; begin -------------------------
sys.path.insert(0, str(ROOT / "near/house"))
import live as house_live  # noqa: E402
import predictions as house_predictions  # noqa: E402
import runtime as house_runtime  # noqa: E402
import sheets as house_sheets  # noqa: E402
# --- house hook: end --------------------------------------------------------------------------------------

RULES = sim.DEFAULT_RULES
PROOF_METHOD = "dev_local_v1"
HOUSE_ACCOUNT = "house.dev.local"
SEED_BATCH = 600
UNREAD_GRACE_S = 180
# The five battle presets: one per fight style, built only from free menu items.
LEGACY_PRESETS = {
    "brawler": dict(style="brawler", loadout=dict(weapon="c-swing", trinket="c-shockwave", body="c-body-builder", head="c-head-builder")),
    "hunter": dict(style="hunter", loadout=dict(weapon="c-shot", trinket="c-blink-strike", body="c-body-speedrunner", head="c-head-speedrunner")),
    "looter": dict(style="looter", loadout=dict(weapon="c-lunge", trinket="c-magnet", body="c-body-degen", head="c-head-degen")),
    "guardian": dict(style="guardian", loadout=dict(weapon="c-lob", trinket="c-bubble", body="c-body-maxi", head="c-head-maxi")),
    "survivor": dict(style="survivor", loadout=dict(weapon="c-zap", trinket="c-chain-storm", body="c-body-speedrunner", head="c-head-maxi")),
}


GUIDE_PRESET_IDS = tuple(name.lower().replace(" ", "-") for name in battle_options.NAMES)
PRESETS = {**LEGACY_PRESETS, **{name: battle_options.preset_kit(RULES, i) for i, name in enumerate(GUIDE_PRESET_IDS)}}


def battle_preset(name: str, rules: dict) -> dict:
    """Resolve guide options against this arena's rules; retain old CLI names for compatibility."""
    if not isinstance(name, str):
        raise ValueError("unknown preset; choose one of " + ", ".join(GUIDE_PRESET_IDS))
    if name in GUIDE_PRESET_IDS:
        return battle_options.preset_kit(rules, GUIDE_PRESET_IDS.index(name))
    if name in LEGACY_PRESETS:
        return LEGACY_PRESETS[name]
    raise ValueError("unknown preset; choose one of " + ", ".join(GUIDE_PRESET_IDS))


def encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decoded(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_ed25519(public_key: str, body: bytes, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(decoded(public_key)).verify(decoded(signature), body)
        return True
    except (InvalidSignature, ValueError):
        return False


def now_ms() -> int:
    return time.time_ns() // 1_000_000


ORIGIN = "http://127.0.0.1:8181"  # the first-look page; the only origin allowed to read /dev/players and /dev/health
LOOPBACK_ORIGIN = re.compile(r"http://(127\.0\.0\.1|localhost)(:[0-9]{1,5})?")  # who may read /house/*


PUBLIC_ORIGIN = re.compile(r"https://[a-z0-9.-]+(:[0-9]{1,5})?")  # a hosted arena's own origin: scheme and name only


# What the start lines say about the chain; a host that adds one (near/chain/hosted_live.py) says so here.
MODE_NOTE = "No wallet, chain or NFT."


def player_token(name: str) -> bool:
    """A joiner's fighter (not a house one). DEV joiners are `dev-` ids; a host that seats players under onchain token
    ids (near/chain/hosted_live.py) widens this to the tokens it registered."""
    return name.startswith("dev-")


def make_contexts(port: int, index: int, public_origin: str | None = None) -> tuple[dict, dict]:
    schema = json.loads((ROOT / "room/protocol.schema.json").read_bytes())
    control = copy.deepcopy(schema["$defs"]["MainnetContext"]["examples"][0])
    control.update(rules_hash=sim.digest(RULES), deployment_id=f"dev-local-r{index}",
                   audience=f"{public_origin or f'https://127.0.0.1:{port}'}/room#control",
                   contract_ids=dict(nft="dev-nft.local", arena="dev-arena.local"))
    result = copy.deepcopy(control)
    result["audience"] = "near:mainnet:" + control["contract_ids"]["arena"] + ":post_batch"
    return control, result


class DevHouse:
    """Keeps the house roster seated through the same bridge calls the engine tests use."""

    def __init__(self, context: dict) -> None:
        self.context = context
        self.arena: server.Arena | None = None
        self.cursor = 0

    def binding(self, name: str) -> dict:
        return {"context": copy.deepcopy(self.context), "grant_id": "grant:" + name, "session_key_id": "key:" + name,
                "member_id": name, "nft_token_id": name, "persona_digest": "a" * 64,
                "account_id": HOUSE_ACCOUNT, "slot_id": name, "generation": "1"}

    def poll(self, control, tick, roster, count, view) -> None:
        bridge = self.arena.bridge
        if not any(player_token(n) for n in self.arena.members):  # keep one ring seat free for a joiner
            count = min(count, 5 - sum(m["profile"]["house"] for m in self.arena.members.values()))
        for step in range(len(roster)):
            if count <= 0:
                return
            name = roster[(self.cursor + step) % len(roster)]
            if name in self.arena.members:
                continue
            b = self.binding(name)
            life = bridge.reserve_life(b)
            if "life_id" not in life:
                continue
            lock = bridge.lock_prediction(b, life["life_id"], None)
            bridge.activate(b, life["life_id"], lock["lock_ref"])
            count -= 1
            self.cursor = (self.cursor + step + 1) % len(roster)


class Round:
    """One arena, one room and one result reader, built together."""

    def __init__(self, dev: "DevRoom", index: int) -> None:
        self.index = index
        self.dev = dev
        # Loopback calls keep the two-argument form (tests stand in their own make_contexts(port, index)).
        self.context, self.result_context = (make_contexts(dev.port, index, dev.public_origin) if dev.public_origin
                                             else make_contexts(dev.port, index))
        self.tmp = Path(dev.data_dir) / f"round-{index}"
        self.tmp.mkdir(parents=True)
        self.security: list[dict] = []
        self.consumed: set[str] = set()
        self.base = now_ms()
        self.arena = None
        slots = SlotStore(self.tmp / "slots", self.context["room_id"], 16, clock=self.vnow)
        self.host = RoomHost(slots, self.context, now_ms=self.vnow, sign=dev.room_sign,
            verify_session=dev.verify_session, key_id="room_key_a", proof_methods=(PROOF_METHOD,),
            consume_nonce=self.consume, ready=lambda: True, admission_open=lambda: True,
            security_event=self.commit_security, battle_mode='behaviour' in RULES, battle_speech=dev.post_speech)
        house = dev.make_house(self.context)  # DevHouse by default, LiveHouse with --house live
        live = isinstance(house, house_live.LiveHouse)
        pick = (lambda b, p: house.pick_resolver(b, p) if b["account_id"] == HOUSE_ACCOUNT else dev.pick(b, p)) if live else dev.pick
        base = secrets.randbelow(1 << 40) * 1000
        self.arena = server.Arena(self.context, [base + i for i in range(SEED_BATCH)], data_dir=self.tmp / "engine",
            room_factory=self.host, profile_provider=dev.profile, identity_resolver=dev.resolve,
            receipt_signer=self.host.sign_receipt, admission_gate=self.host.admission_ready,
            life_guard=self.life_guard, server_time_ms=self.vnow, pick_resolver=pick,
            house_runtime=house, dev_host=True,  # this host seats `dev-` ids by design; a production host refuses them
            prediction_log=house.log if live else None, record=dev.record)
        self.house = house
        self.arena.battle_guard = lambda who, text: dev.feed.guard.check(text, who=who)
        # board 1's panel: item names for the bench card, the fighter's own log, owner notes and receipts
        self.arena.item_names = dev.item_names
        self.arena.fighter_event = dev.fighter_event
        self.arena.battle_note = dev.post_note
        self.arena.battle_receipt_seen = dev.receipt_seen
        house.attach(self.arena) if live else setattr(house, "arena", self.arena)
        self.feed = dev.feed
        apply_intent = self.arena.bridge.apply

        def guarded_intent(binding: dict, message: dict) -> dict:
            if self.host._battle_mode or message.get('kind') != 'intent':
                return apply_intent(binding, message)
            key = sim.digest([self.arena.context, binding["grant_id"], binding["session_key_id"], message["sequence"]])
            first = key not in self.arena.receipts
            reply = apply_intent(binding, message)
            line = message["payload"].get("say")
            if first and reply.get("state") == "accepted" and line is not None:
                who = binding["nft_token_id"]
                posted = self.feed.post(who, line, source="player", tick=dev.feed_tick())
                dev.speech_results[who] = dict(sequence=message["sequence"], speech=posted)
            return reply

        self.arena.bridge.apply = guarded_intent
        boundary = self.host.service.life_boundary
        house_grants = {house.binding(n)["grant_id"] for n in RULES["house"]}
        self.deferred_notices: list[str] = []

        def life_boundary(grant_id: str) -> None:
            # House trenchies are seated through the bridge, not the room, so they hold no grant to notify. A notice
            # that reserves a life enqueues an input two ticks ahead: after the step to the segment's last 2 ticks that
            # lands in the next segment, so it waits until the segment turns over.
            if grant_id in house_grants:
                return None
            if self.in_boundary():
                self.deferred_notices.append(grant_id)
                return None
            return boundary(grant_id)

        self.host.service.life_boundary = life_boundary
        # DEV boundary guard. An input enqueued in the last input_delay ticks of a segment is journalled in this
        # segment but applied in the next, and the result reader refuses a segment that holds one. The room-facing
        # routes below refuse such calls for a moment; the engine's own scheduling and life notices step aside for
        # the same ticks.
        schedule = self.arena._schedule

        def guarded_schedule() -> None:
            if self.in_boundary():
                return None
            while self.deferred_notices:
                boundary(self.deferred_notices.pop(0))
            return schedule()

        self.arena._schedule = guarded_schedule
        self.records = EngineRecords(self.arena.store, self.tmp / "wire.sqlite", self.context, self.result_context,
            key_id="room_key_a", sign=dev.room_sign, verify=lambda key, body, sig: key == "room_key_a" and verify_ed25519(dev.room_public, body, sig),
            key_allowed=lambda key: key == "room_key_a")
        self.host.service.records = self.records
        self.ever_dev = False
        self.claimed_at = 0.0
        self.result_served = False
        self.corner_lives: dict[str, dict] = {}
        advance = self.arena.advance

        def advance_with_corner(ticks: int = 1) -> None:
            sim.unsigned(ticks, "ticks")
            for _ in range(ticks):
                forecasts = self.corner_forecasts()
                drops = set(self.arena.sim.state["drops"])
                advance()
                self.capture_corner(forecasts)
                dev.log_fighter_events(self.arena, drops)
                dev.post_reflexes(self.arena)

        self.arena.advance = advance_with_corner

    def corner_forecasts(self) -> dict[str, dict | None]:
        """Only the public forecast fields, captured before a seal can prune old locks."""
        forecasts = {}
        for name in self.dev_members():
            life = self.arena.members[name]["life_id"]
            pick = self.arena.locks.get(life, {}).get("public", {}).get("pick")
            forecasts[life] = None if pick is None else {k: copy.deepcopy(pick["payload"][k]) for k in ("spread_bps", "zero_bps")}
        return forecasts

    def capture_corner(self, forecasts: dict[str, dict | None]) -> None:
        """Keep the last public life outcome per local fighter across segment rollover."""
        for event in self.arena.sim.state["events"]:
            name = event.get("fighter", "")
            if not player_token(name) or event["kind"] not in ("ko", "leave"):
                continue
            fighter = self.arena.sim.state["fighters"].get(name)
            if fighter is None:
                continue
            life = event.get("life_id", fighter["life_id"])
            self.corner_lives[name] = dict(life_id=life, ko_count=event.get("life_kos", fighter["life_kos"]),
                                          ended=event["kind"], ended_by=event.get("source"),
                                          prediction=copy.deepcopy(forecasts.get(life)))

    def in_boundary(self) -> bool:
        return self.arena.sim.state["tick"] % RULES["segment_ticks"] >= RULES["segment_ticks"] - RULES["input_delay"]

    def vnow(self) -> int:
        """Room time is sim time (50 ms a tick from the round's start): a stalled or paused sim stalls every deadline."""
        return self.base + (0 if self.arena is None else self.arena.sim.state["tick"] * 50)

    def consume(self, nonce: str, expires_at: str) -> bool:
        if nonce in self.consumed or int(expires_at) <= self.vnow():
            return False
        self.consumed.add(nonce)
        return True

    def commit_security(self, event: dict) -> bool:
        self.security.append(copy.deepcopy(event))
        return True

    def life_guard(self, binding: dict) -> bool:
        return True if binding["account_id"] == HOUSE_ACCOUNT else self.host.life_guard(binding)

    def dev_members(self) -> list[str]:
        return [n for n in self.arena.members if player_token(n)]


class DevRoom:
    def __init__(self, port: int, data_dir: str, house: str = "dev", budget_mode: str = "auto",
                 house_client=None, *, public_origin: str | None = None, state_dir: str | None = None) -> None:
        self.port = port
        self.data_dir = data_dir
        # Hosted (make play behind nginx): the public origin is the one more name the Host and Origin checks accept,
        # the client address comes from nginx's X-Real-IP, and /dev/shutdown does not exist. None = loopback only.
        if public_origin is not None and not PUBLIC_ORIGIN.fullmatch(public_origin):
            raise ValueError("--public-origin is https://<name>[:port], lower case, with no path")
        self.public_origin = public_origin
        self.public_host = public_origin.split("://", 1)[1] if public_origin else None
        self.bind = "127.0.0.1"
        # The house's meter, predictions log and status live in <state>/house: a hosted arena passes a persistent
        # state dir, so a restart never resets the day's spend. Default: the data dir, as before.
        self.house_parent = Path(state_dir) if state_dir is not None else Path(data_dir)
        # The public record (arena/predict.py): one for the host, beside the house's state, shared by every round's
        # arena, so a round restart or a host start keeps the day's rows and the boards read the whole day.
        self.record = predict.Record(self.house_parent / "record.jsonl")
        # house hook: with --house live, one meter and one predictions log shared by every round's LiveHouse. The
        # one public feed for every producer (house and player lines) is the host's `self.feed` below.
        self.house_kind = house
        self.house_client = house_client  # tests pass a scripted model; a live run builds the NEAR AI Cloud client
        self.house_sheets = house_sheets.load()
        self.house_model = "house (deterministic tick policy)"
        if house == "keyed":  # no model key: LiveHouse seating, the tick policy, labelled keyed lines, the autopilot chip
            self.house_client, self.house_budget = house_live.NoModel(), house_live.NoKeyBudget()
            self.house_log = house_predictions.PredictionLog(self.house_parent / "house")
            self.house_model = house_live.KEYED_LABEL
        elif house == "live":
            if house_client is None and not os.environ.get(house_live.KEY_ENV):
                raise house_live.KeyMissing(f"--house live needs {house_live.KEY_ENV} in the process environment "
                                            "(from the env file outside the repo); the default --house dev needs no key")
            hdir = self.house_parent / "house"
            self.house_budget = house_runtime.Budget(house_runtime.JsonMeter(hdir / "spend.json"), budget_mode, clock=time.time)
            self.house_log = house_predictions.PredictionLog(hdir)
            self.house_model = house_live.MODEL_LABEL
        elif house != "dev":
            raise ValueError("--house is dev, keyed or live")
        self.room_key = Ed25519PrivateKey.generate()
        self.room_public = encoded(self.room_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        self.admin = encoded(os.urandom(18))  # printed once at start; /dev/shutdown needs it
        self.hold_tokens: dict[str, float] = {}
        self.identities: dict[str, dict] = {}
        self.by_key: dict[str, dict] = {}
        self.codes: dict[str, dict] = {}
        self.house_games = {p.stem: json.loads(p.read_bytes())['game'] for p in sorted((ROOT / 'near/lore/personas').glob('*.json'))}
        self.guard_names = [game['name'] for game in self.house_games.values()]
        self.feed = PublicFeed(Guard.from_env(self.guard_names), rate_ticks=RULES.get('behaviour', {}).get('say_ticks', 600))
        self.feed.game_of = self.game_for
        self.speech_results: dict[str, dict] = {}
        self.reflex_speech_results: dict[str, dict] = {}
        # board 1's panel: names for item ids, and per player fighter its own log (public events in /dev/corner; the
        # owner's orders, replies and receipts only through its door code) and the plan use its session reported
        kits = json.loads((ROOT / "near/lore/kits.json").read_bytes())
        self.item_names = {row["id"]: row["name"] for row in kits["items"]}
        self.fighter_logs: dict[str, list[dict]] = {}
        self.plan_use: dict[str, dict] = {}
        self.feed_offset = 0
        self.round_index = 0
        self.round = self._new_round()
        self.clients: dict = {}  # writer -> True when it asked for the compact frames (?codec=1)
        self.live_clients: dict = {}  # writer -> authenticated live control/event peer
        self.tables = None
        self.styles = SpectatorStyles(self.round.arena.sim, dev_brawl.frame)
        self.client_tables: dict = {}  # writer -> table_id of the last tables frame it was sent
        self.latest_codec = None
        self.social_bytes = b""
        self.social_clients: dict = {}
        self.refresh_frames()
        self.dropped = 0
        self.slowest = 0.0
        self.stop = False
        self.hold_until = 0.0
        self.resyncs = 0

    # --- house hook ------------------------------------------------------------------------------------
    def make_house(self, context: dict):
        if self.house_kind in ("live", "keyed"):
            return house_live.LiveHouse(context, self.house_parent, self.feed, account_id=HOUSE_ACCOUNT,
                                        budget=self.house_budget, log=self.house_log, sheets=self.house_sheets,
                                        client=self.house_client, feed_tick=getattr(self, "feed_tick", None),
                                        model_label=self.house_model,
                                        # battle mode whenever the rules table has the behaviour input (integer-13 on)
                                        battle="behaviour" in RULES.get("input_kinds", ()))
        return DevHouse(context)

    def house_roster(self) -> dict:
        """The public roster projection: admitted members, public states, the house's meter; never a player's spend."""
        h = self.round.house
        if isinstance(h, house_live.LiveHouse):
            return h.public_roster()
        return house_live.public_roster_of(self.round.arena, self.house_sheets, self.house_model)

    def house_predictions(self) -> bytes:
        """The public per-AI predictions log (F79), the JSONL file exactly as written; empty for the deterministic house."""
        log = getattr(self, "house_log", None)
        return log.path.read_bytes() if log is not None and log.path.exists() else b""

    # --- DEV adapters -------------------------------------------------------------------------------
    def room_sign(self, body: bytes) -> str:
        return encoded(self.room_key.sign(body))

    def verify_session(self, public_key: dict, body: bytes, signature: str) -> bool:
        rec = self.by_key.get(public_key.get("public_key"))
        return rec is not None and verify_ed25519(rec["session_public_key"]["public_key"], body, signature)

    def game_for(self, who: str) -> dict:
        if who in self.house_games:
            return self.house_games[who]
        return self.identities.get(who, {}).get('game', {'temperament': 'Restless'})

    def post_speech(self, binding: dict, payload: dict) -> dict:
        who = binding['nft_token_id']
        posted = self.feed.post(who, payload['text'], source='player', tick=self.feed_tick(), emoji=payload.get('emoji'))
        self.speech_results[who] = dict(sequence=payload['sequence'], speech=posted)
        return posted

    def post_reflexes(self, arena) -> None:
        for event in arena.sim.state['events']:
            if event['kind'] != 'say':
                continue
            who = event['fighter']
            member = arena.members.get(who)
            if member is None or member['released']:
                continue
            source = 'house' if member['profile']['house'] else 'player'
            speech = self.feed.post(who, event['text'], source=source, tick=self.feed_tick(), emoji=None)
            self.reflex_speech_results[who] = dict(tick=arena.sim.state['tick'], index=event['index'], speech=speech)

    # --- board 1: the fighter's own log --------------------------------------------------------------
    LOG_MAX = 50

    def display_name(self, who: str | None) -> str:
        if who is None:
            return "the ring"
        if who in self.house_games:
            return self.house_games[who].get("tag") or self.house_games[who].get("name") or who
        return self.identities.get(who, {}).get("name") or who

    def fighter_event(self, who: str, kind: str, text: str) -> None:
        """A public fact about a player's fighter, for its panel's log; house fighters keep none."""
        if not player_token(who):
            return
        log = self.fighter_logs.setdefault(who, [])
        log.append(dict(at_ms=now_ms(), kind=kind, text=text))
        del log[:-self.LOG_MAX]

    def log_fighter_events(self, arena, drops_before: set) -> None:
        tick_s = arena.sim.rules["respawn_ticks"] // arena.sim.rules["tick_hz"]
        for event in arena.sim.state["events"]:
            who, kind = event.get("fighter"), event["kind"]
            f = arena.sim.state["fighters"].get(who) if who else None
            if f is None:
                continue
            if kind == "respawn":
                log = self.fighter_logs.get(who, [])
                if any(row["kind"] == "joined" for row in log):
                    self.fighter_event(who, "respawn", f"Back in the ring. Life {f['life_number']}.")
                else:
                    self.fighter_event(who, "joined", f"Snapped in. Life {f['life_number']}.")
            elif kind == "ko":
                dropped = [d["row"] for key, d in sorted(arena.sim.state["drops"].items())
                           if key not in drops_before and d["owner"] == who]
                lost = ("Dropped " + self.item_names.get(dropped[0], dropped[0]) + ".") if dropped else "Dropped nothing."
                member = arena.members.get(who, {})
                after = ("Stays on the bench." if member.get("bench_hold") else f"Life {f['life_number'] + 1} in {tick_s} s.")
                self.fighter_event(who, "kod", f"KO'd by {self.display_name(event.get('source'))}. {lost} {after}")
                source = event.get("source")
                if source:
                    self.fighter_event(source, "ko", f"KO'd {self.display_name(who)}. +1 KO.")
            elif kind == "grab" and not event.get("destroyed"):
                self.fighter_event(who, "pickup", "Picked up " + self.item_names.get(event["row"], event["row"]) + ".")

    def _order_entry(self, who: str, seq: str) -> dict:
        log = self.fighter_logs.setdefault(who, [])
        for row in reversed(log):
            if row["kind"] == "order" and row["seq"] == seq:
                return row
        row = dict(at_ms=now_ms(), kind="order", seq=seq, order=None, reply=None, why=None, receipt=None)
        log.append(row)
        del log[:-self.LOG_MAX]
        return row

    def receipt_seen(self, binding: dict, request: dict, ack: dict) -> None:
        """Every behaviour ACK of a player fighter, kept beside the order it answers (the owner's panel)."""
        who = binding["nft_token_id"]
        if request.get("kind") != "behaviour" or not player_token(who):
            return
        row = self._order_entry(who, str(request["sequence"]))
        row["receipt"] = dict(status=ack.get("status"), summary=ack.get("summary"), applies_in_ms=ack.get("applies_in_ms"))

    def post_note(self, binding: dict, payload: dict) -> str:
        """An agent session's note for its owner: never the feed, never the engine journal."""
        who = binding["nft_token_id"]
        if "plan" in payload:
            self.plan_use[who] = dict(week_used_pct=payload["plan"]["week_used_pct"], reported_at_ms=now_ms())
        texts = {k: payload[k] for k in ("order", "reply", "why") if k in payload}
        if texts:
            row = self._order_entry(who, payload.get("seq") or str(payload["sequence"]))
            row.update(texts)
        return "Kept for your owner's panel" + (" (plan use recorded)." if "plan" in payload else ".")

    def code_log(self, code: str) -> dict:
        """The owner's panel for an agent-driven trenchie, read with the door code the guide page holds."""
        row = self.codes.get(code) if isinstance(code, str) else None
        if row is None or (not row["joined"] and time.time() >= row["expires_at"]):
            raise ValueError("code expired or unknown; ask the AI door for a new code")
        if not row["joined"]:
            return dict(joined=False, state="pending")
        who = row["claimed_by"]
        arena = self.round.arena
        member, f = arena.members.get(who), arena.sim.state["fighters"].get(who)
        bench = arena.bridge.bench_view(who) if member is not None else {}
        state = ("home" if member is None else "ring" if f is not None and f["state"] == "alive"
                 else "held" if bench.get("held") else "bench")
        plan = self.plan_use.get(who, {})
        return dict(joined=True, state=state, fighter_id=who, name=row["name"], agent=row["agent"],
                    life=None if f is None else f["life_number"], hp=None if f is None else f["hp"],
                    max_hp=None if f is None else f["max_hp"],
                    plan=dict(stop_pct=row.get("plan_stop_pct"), week_used_pct=plan.get("week_used_pct"),
                              reported_at_ms=plan.get("reported_at_ms"),
                              # the session stops sending orders at its door limit (snap.py live does the stopping)
                              stopped=(row.get("plan_stop_pct") is not None and plan.get("week_used_pct") is not None
                                       and plan["week_used_pct"] >= row["plan_stop_pct"])),
                    log=copy.deepcopy(self.fighter_logs.get(who, [])))

    def resolve(self, request: dict) -> dict:
        challenge = request["challenge"]
        rec = self.identities.get(challenge["nft_token_id"])
        proof = request["proof"]
        if (rec is None or proof.get("method_id") != PROOF_METHOD or rec["account_id"] != challenge["account_id"]
                or not verify_ed25519(rec["session_public_key"]["public_key"], b"dev-wallet|" + canonical_bytes(request, exclude=("proof",)), proof["proof_bytes"])):
            return server.error("proof_required")
        return {"owner": {"context": copy.deepcopy(self.round.context), "account_id": rec["account_id"],
                "nft_token_id": rec["nft_token_id"], "persona_digest": request["persona_digest"],
                "ownership_kind": "owner", "custody_reservation_id": None, "checked_at": str(self.round.vnow())},
                "play_status": "eligible", "chain_height": "1", "sale_control_allowed": True}

    def profile(self, binding: dict) -> dict:
        name = binding["nft_token_id"]
        if binding["account_id"] == HOUSE_ACCOUNT:
            row = RULES["house"][name]
            return {"house": True, "public_name": name, "model": self.house_model, "style": row["style"],
                    "loadout": sim.rules_dict(row["kit"]), "bag": {}}
        rec = self.identities[name]
        preset = battle_preset(rec["preset"], self.round.arena.sim.rules)
        public_name = "DEV " + rec["name"] + (" · name unchecked" if not rec.get("name_check", {}).get("nameChecked", False) else "")
        return {"house": False, "public_name": public_name, "model": "dev", "style": rec.get("persona", {}).get("fightStyle", preset["style"]),
                "loadout": dict(preset["loadout"]), "bag": {}}

    def pick(self, binding: dict, payload: dict) -> dict:
        row = payload["loadout"]["menu_row"]
        return dict(battle_preset(row, self.round.arena.sim.rules)["loadout"])

    def create_identity(self, name: str, preset: str, public_key: str, *, sheet: dict | None = None, code: str | None = None, look: dict | None = None) -> dict:
        pairing = self.code_status(code, claim=True) if code else None
        if pairing is not None:
            sheet = pairing.get("sheet") or sheet
            look = pairing.get("look") or look
            name = pairing.get("name") or name
            preset = pairing.get("preset") or preset
        persona = check_sheet(sheet) if sheet is not None else None
        look = check_look(look)
        if look is not None and persona is None:
            raise ValueError("look needs a creator sheet; pass --sheet with --look")
        if look is not None:
            persona["look"] = look
        if persona is not None:
            name = persona["name"]
        name_check = check_display_name(name, persona["tag"] if persona is not None else name)
        slug = "".join(c for c in name.lower() if c.isalnum())[:16]
        if not slug or preset not in PRESETS:
            raise ValueError("name needs letters or digits; choose a preset from " + ", ".join(GUIDE_PRESET_IDS))
        try:
            if len(decoded(public_key)) != 32 or len(public_key) != 43:
                raise ValueError
            Ed25519PublicKey.from_public_bytes(decoded(public_key))
        except ValueError:
            raise ValueError("public_key must be a 32-byte Ed25519 public key, base64url without padding") from None
        token = "dev-" + slug
        if token in self.round.arena.members:
            raise ValueError(f"{token} is seated right now; pick another name or `stop` that session first")
        self.maybe_restart("a DEV identity with no DEV trenchie present")
        self.round.ever_dev = True  # this round now belongs to the DEV joiner: it is not restarted under them
        self.round.claimed_at = time.monotonic()
        old = self.identities.get(token)
        if old is not None:
            self.by_key.pop(old["session_public_key"]["public_key"], None)
        rec = {"name": slug, "preset": preset, "nft_token_id": token, "account_id": f"dev-{slug}.local",
               "persona_digest": sheet_digest(sheet) if sheet is not None else hashlib.sha256(f"dev|{slug}|{preset}".encode()).hexdigest(),
               "session_public_key": {"algorithm": "ed25519", "public_key": public_key}}
        rec['game'] = {'temperament': persona['temperament'] if persona is not None else 'Restless'}
        if sheet is not None and 'emoji' in sheet['game']:
            rec['game']['emoji'] = copy.deepcopy(sheet['game']['emoji'])
        if persona is not None:
            rec["name"], rec["persona"] = persona["name"], persona
        if pairing is not None:
            pairing["claimed_by"] = token
            rec["pair_code"] = code
        rec["name_check"] = name_check
        self.identities[token] = rec
        previous_guard = self.feed.guard
        updated_guard = Guard(previous_guard.blocklist, self.guard_names + [r["name"] for r in self.identities.values()])
        updated_guard.log = previous_guard.log
        self.feed.guard = updated_guard
        self.by_key[public_key] = rec
        print(f"snap_local: DEV identity registered: {token} ({preset}); no wallet, chain or NFT is involved", flush=True)
        return self.identity_reply(rec)

    def identity_reply(self, rec: dict) -> dict:
        """What a joiner needs to sign in: its identity plus this round's public room material."""
        name_check = rec["name_check"]
        return {"label": "DEV", "name": rec["name"], "name_checked": name_check["nameChecked"], "name_notice": name_check["nameNotice"],
                "preset": rec["preset"], "nft_token_id": rec["nft_token_id"], "account_id": rec["account_id"],
                "persona_digest": rec["persona_digest"], "session_public_key": rec["session_public_key"],
                "room_public_key": self.room_public, "proof_method": PROOF_METHOD, "key_id": "room_key_a",
                "context": self.round.context, "result_context": self.round.result_context, "presets": sorted(PRESETS)}

    def rejoin_identity(self, args: dict) -> dict:
        """A live session whose round restarted signs in again as the same trenchie: the identity its session key
        already holds, with the new round's contexts. It registers nothing and never restarts a round.

        Only the session key itself may ask: the request carries that key's signature over this round's index and a
        wall-clock time within REJOIN_WINDOW_MS (battle_protocol.rejoin_message). Anything else is refused before
        any state changes, so a stranger who knows a public key can't refresh this round's claim or hold it."""
        public_key = args.get("public_key")
        rec = self.by_key.get(public_key) if isinstance(public_key, str) else None
        if rec is None:
            raise ValueError("no DEV identity holds that session key; join again")
        round_index, at, proof = args.get("round"), args.get("at"), args.get("sig")
        if type(round_index) is not int or type(at) is not int or not isinstance(proof, str):
            raise ValueError("rejoin needs round, at and sig: the session key's signature (snap.py live sends it)")
        if round_index != self.round_index:
            raise ValueError(f"rejoin is signed for round {round_index}; this is round {self.round_index}")
        if abs(time.time() * 1000 - at) > battle_protocol.REJOIN_WINDOW_MS:
            raise ValueError("rejoin proof is stale; sign a fresh one")
        if not verify_ed25519(public_key, battle_protocol.rejoin_message(round_index, public_key, at), proof):
            raise ValueError("rejoin proof does not verify with that session key")
        # Each proof is good once: an observer can't replay it inside its window. A proof is the signed message (this
        # round, this key, this time), not the signature's spelling: the base64url decoder takes non-canonical
        # spellings, so one signature has several. Proofs older than the window are dropped, because the time check
        # above already refuses them.
        now_ms = time.time() * 1000
        used = self.__dict__.setdefault("rejoin_proofs_used", {})
        for old_proof in [m for m, at_ms in used.items() if now_ms - at_ms > battle_protocol.REJOIN_WINDOW_MS]:
            del used[old_proof]
        signed = battle_protocol.rejoin_message(round_index, public_key, at)
        if signed in used:
            raise ValueError("rejoin proof already used; sign a fresh one")
        used[signed] = at
        if rec["nft_token_id"] in self.round.arena.members:
            raise ValueError(f"{rec['nft_token_id']} is already in this round")
        self.round.ever_dev = True
        self.round.claimed_at = time.monotonic()
        print(f"snap_local: DEV identity rejoined round {self.round_index}: {rec['nft_token_id']}", flush=True)
        return self.identity_reply(rec)

    def issue_code(self, args: dict) -> dict:
        """A short-lived local door rendezvous, never a grant or wallet authority."""
        if not isinstance(args, dict):
            raise ValueError("code request needs a JSON object with agent and name")
        if args.get("agent") not in ("claude-code", "codex"):
            raise ValueError("agent must be claude-code or codex")
        now = time.time()
        # a joined code stays: its page reads the owner's panel with it while that trenchie is in the arena
        self.codes = {k: v for k, v in self.codes.items()
                      if v["expires_at"] > now or (v["joined"] and v["claimed_by"] in self.round.arena.members)}
        if sum(not v["joined"] for v in self.codes.values()) >= 64:
            raise ValueError("too many pending codes; wait ten minutes and retry")
        if args.get("sheet") is not None:
            check_sheet(args["sheet"])
        look = check_look(args.get("look"))
        preset = args.get("preset", "hunter")
        if preset not in PRESETS:
            raise ValueError("unknown preset; choose " + ", ".join(GUIDE_PRESET_IDS))
        name = args.get("name") or "newcomer"
        if not isinstance(name, str) or len(name) > 64:
            raise ValueError("name must be text, at most 64 characters")
        stop = args.get("plan_stop_pct")
        if stop is not None and stop not in (5, 10, 20):
            raise ValueError("plan_stop_pct is 5, 10 or 20 (the share of the plan's week), or left out")
        code = secrets.token_urlsafe(12)
        self.codes[code] = dict(expires_at=now + 600, name=name, sheet=args.get("sheet"), preset=preset,
                                look=look, claimed_by=None, joined=False, agent=args["agent"], plan_stop_pct=stop)
        base = self.public_origin or f"http://127.0.0.1:{self.port}"
        script = "near/arena/snap.py" if self.public_origin else shlex.quote(str(HERE / "snap.py"))  # hosted: the agent's own clone
        return dict(code=code, expires_at=int((now + 600) * 1000),
                    snap_url=f"{base}/SNAP.md", stub=False, dev=True,
                    # Battle mode on the creator's trenchie: one live session, orders in through a private pipe.
                    command=f"python3 -I {script} --url {base} live --code {code} --preset {preset} --accept-terms 1"
                            ' --fifo "$PWD/orders.fifo"',
                    state="pending")

    def code_status(self, code: str, *, claim: bool = False) -> dict:
        if not isinstance(code, str):
            raise ValueError("code must be text; copy a fresh code from the AI door")
        row = self.codes.get(code)
        if row is None or time.time() >= row["expires_at"]:
            raise ValueError("code expired or unknown; ask the AI door for a new code")
        if claim and row["claimed_by"] is not None:
            raise ValueError("code already used; ask the AI door for a new code")
        return row

    def mark_paired(self, token: str) -> None:
        """Called only after the room accepts signed control authentication."""
        rec = self.identities.get(token, {})
        code = rec.get("pair_code")
        if code and token in self.round.arena.members:
            row = self.codes.get(code)
            if row is not None and row["claimed_by"] == token:
                row["joined"] = True
                row["name"] = rec["name"]

    # --- rounds -------------------------------------------------------------------------------------
    def feed_tick(self) -> int:
        """Monotonic sim ticks across round restarts; respawning never resets the speech cap."""
        return self.feed_offset + self.round.arena.sim.state["tick"]

    def _new_round(self) -> Round:
        self.round_index += 1
        self.reflex_speech_results.clear()
        self.fighter_logs.clear()
        self.plan_use.clear()
        return Round(self, self.round_index)

    def maybe_restart(self, why: str) -> None:
        """A join with no DEV trenchie present starts segment:0 now, unless a result is still pending."""
        r = self.round
        if r.dev_members() or (r.ever_dev and r.arena.segment_index == 0 and not r.arena.failed):
            return
        wait = UNREAD_GRACE_S - (time.monotonic() - r.claimed_at)
        if r.ever_dev and not r.result_served and not r.arena.failed and wait > 0:
            raise ValueError(f"round {self.round_index} still holds a result its player has not read; "
                             f"retry in {int(wait) + 1} s, or read it first with `snap.py result`")
        self.feed_offset = self.feed_tick()
        self.round = self._new_round()
        self.refresh_frames()
        print(f"snap_local: round {self.round_index} started ({why})", flush=True)

    @staticmethod
    def guarded(path: str, body: bytes) -> bool:
        """Calls that become engine inputs: a join, or a control frame that is an order or a prediction."""
        if path == "/room/join":
            return True
        try:
            return json.loads(body).get("kind") in ("intent", "prediction")
        except (ValueError, AttributeError):
            return False

    def start_hold(self) -> None:
        """Freeze the sim for one join handshake (up to 10 s). Callers are unauthenticated, so repeats and other
        callers never extend it, and a new freeze waits 5 s after the last one ended."""
        now = time.monotonic()
        if now >= self.hold_until + 5:
            self.hold_until = now + 10

    def why(self, segment_id: str) -> dict:
        """Say which check of the sealed-record projection refuses a segment, and which commands cross its end."""
        from portable_records import _project
        from room.ledger import Refusal
        try:
            record = self.round.arena.store.segment(segment_id)
        except (FileNotFoundError, KeyError, ValueError):
            return {"segment_id": segment_id, "sealed": False}
        end = RULES["segment_ticks"] * (int(segment_id.split(":")[1]) + 1)
        crossing = [{"kind": row["value"]["kind"], "fighter": row["value"]["fighter_id"], "tick": row["value"]["tick"]}
                    for row in record["commands"] if row["kind"] == "input" and row["value"]["tick"] >= end]
        try:
            _project(record)
            return {"segment_id": segment_id, "sealed": True, "refused": False, "crossing_commands": crossing}
        except Refusal as exc:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            return {"segment_id": segment_id, "sealed": True, "refused": True, "code": str(exc),
                    "check": f"{frame.name} (portable_records.py:{frame.lineno})", "crossing_commands": crossing}

    def players(self) -> list[dict]:
        a = self.round.arena
        out = []
        for name in a.members:
            if player_token(name):
                rec = self.identities.get(name, {})
                f = a.sim.state["fighters"].get(name)
                out.append({"label": "DEV", "fighter_id": name, "name": rec.get("name"), "preset": rec.get("preset"),
                            "name_checked": rec.get("name_check", {}).get("nameChecked", False), "name_notice": rec.get("name_check", {}).get("nameNotice"),
                            "state": f["state"] if f else "bench", "life_id": a.members[name]["life_id"]})
        return out

    def corner(self, name: str) -> dict:
        """Public respawn data. Missing pickup provenance is explicitly untracked."""
        arena = self.round.arena
        member = arena.members.get(name)
        if member is None or not player_token(name):
            raise ValueError("unknown DEV fighter; choose fighter_id from /dev/players")
        game = arena.sim
        fighter = game.state["fighters"].get(name)
        state = "bench" if fighter is None else ("ring" if fighter["state"] == "alive" else "down" if fighter["state"] == "bench" and fighter["deaths"] else "bench")
        respawn_tick = fighter.get("respawn_at") if fighter is not None and state == "down" else None
        floor = [dict(serial_id=key, item_id=drop["row"], owner=name, x_milli=drop["x"], y_milli=drop["y"],
                      returns_at_ms=self.round.base + drop["expires_at"] * 1000 // game.rules["tick_hz"])
                 for key, drop in sorted(game.state["drops"].items()) if drop["owner"] == name]
        pending = []
        if member["awaiting_life"] and member["life_id"] in arena.locks:
            pending.append(dict(kind="respawn_pick", text="Your pick is locked for the coming life."))
        public = [dict(row) for row in self.fighter_logs.get(name, []) if row["kind"] != "order"][-20:]
        return dict(fighter_id=name, state=state,
                    hp=None if fighter is None else fighter["hp"], max_hp=None if fighter is None else fighter["max_hp"],
                    bench=arena.bridge.bench_view(name), events=public,
                    respawn_at_ms=None if respawn_tick is None else self.round.base + respawn_tick * 1000 // game.rules["tick_hz"],
                    last_life=copy.deepcopy(self.round.corner_lives.get(name)), taken=[], floor=floor, pending=pending,
                    untracked={"taken": "not tracked: pickup events do not retain previous holder and serial provenance",
                               "pending.item_returns": "not tracked: the engine has floor expiry timers, not settled return receipts"},
                    floor_timer_kind="floor_expiry")

    def check_prediction_menu(self, body: bytes) -> None:
        """Name the legal local menu ids before forwarding a prediction to the closed room API."""
        message = json.loads(body)
        if not isinstance(message, dict) or message.get("kind") != "prediction":
            return
        payload = message.get("payload")
        loadout = payload.get("loadout") if isinstance(payload, dict) else None
        if isinstance(loadout, dict):
            battle_preset(loadout.get("menu_row"), self.round.arena.sim.rules)

    def health(self) -> dict:
        a = self.round.arena
        chain = a.health().get("chain")
        return {**({"chain": copy.deepcopy(chain)} if chain is not None else {}), "dev": True, "round": self.round_index, "tick": a.sim.state["tick"], "segment": a.segment_id,
                "spectators": len(self.clients), "dev_players": len(self.round.dev_members()), "failed": a.failed,
                "dropped_sends": self.dropped, "clock_resyncs": self.resyncs, "slowest_step_ms": round(self.slowest * 1000, 2),
                "rules_hash": a.sim.rules_hash, "claims": "DEV: no wallet, chain or NFT; contract ids are dev-*.local; the protocol's network field reads mainnet because its schema defines no other context"}

    def social_frame(self) -> bytes:
        """Display-only checked personas and guarded public feed, outside replay/tick bytes."""
        players = []
        for token in self.round.dev_members():
            rec = self.identities.get(token, {})
            persona = {**rec.get("persona", {}), **rec.get("name_check", {})}
            players.append(dict(trenchieId=token, name=rec.get("name", token),
                                tag=rec.get("name", token), **{k: v for k, v in persona.items() if k not in ("name", "tag")}))
        feed = getattr(self, "feed", None)
        rows = feed.since(0) if feed is not None else []
        return dev_brawl.frame(json.dumps(dict(type="spectator_social", version=1,
                                      players=players, feed=rows[-64:], lives=self.public_lives(),
                                      names=self.public_names()), separators=(",", ":")).encode())

    def public_lives(self) -> dict:
        """Each fighter's current life as the arena page draws its name tag: {fighter: {life, level, kos, points}}.

        level is the life's predicted level (1-4, "L or more KOs") read from its locked pick exactly as the seal row
        reads it (predict.read_level), or None when it predicted nothing or a pick that does not count; kos is its KOs
        this life; points are the reward points a correct prediction earns (the seal row's own outcome at the base
        rate of its lock). All public: the pick is in the public record and the KOs are in the snapshot. A life's
        level and points are read once its lock exists and kept until the life changes."""
        arena = self.round.arena
        cache = getattr(self, "_life_reads", None)
        if cache is None or cache[0] is not arena:
            cache = self._life_reads = (arena, {})
        reads, out = cache[1], {}
        for name, f in arena.sim.state["fighters"].items():
            if f["state"] == "left":
                continue
            life = f["life_id"]
            got = reads.get(life)
            if got is None:
                lock = arena.locks.get(life)
                pick = lock["public"].get("pick") if lock is not None else None
                level = (predict.read_level(arena.sim.rules, pick["payload"]["spread_bps"], pick["payload"]["zero_bps"])[0]
                         if pick is not None else None)
                points = (predict.outcome(arena.sim.rules, level, level, arena._base_rate_at(lock.get("at_ms")))["reward_points"]
                          if level is not None else 0)
                got = (level, points)
                if lock is not None:   # no lock yet: read it again next tick
                    reads[life] = got
            out[name] = dict(life=life, level=got[0], kos=f["life_kos"], points=got[1])
        live = {f["life_id"] for f in arena.sim.state["fighters"].values()}
        for life in [k for k in reads if k not in live]:
            del reads[life]
        return out

    def public_names(self) -> dict:
        """Display names for every trenchie this host registered, so a board row for one who has left still reads
        as a name, never an id."""
        return {token: rec.get("name", token) for token, rec in sorted(self.identities.items())}

    def refresh_frames(self) -> None:
        """The plain snapshot every tick; the compact tick frame (and its tables, when the roster changed) only if wanted."""
        arena = self.round.arena
        self.latest = arena.snapshot_bytes
        if any(self.clients.values()) or self.tables is None:
            self.tables = codec.tables_for(arena.sim)
            self.latest_codec = codec.encode_tick(arena.sim, self.tables)
        else:
            self.latest_codec = None

    # --- HTTP ----------------------------------------------------------------------------------------
    def own_hosts(self) -> set[str]:
        """The Host headers this host answers (DNS rebinding guard): its loopback name and port, plus the public name."""
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}", *((self.public_host,) if self.public_host else ())}

    def client_ip(self, writer, headers: dict) -> str:
        """The peer address; hosted, nginx's X-Real-IP (set by nginx on every request, never appended to), so the
        room's per-address limits see each visitor rather than the proxy. Loopback-only hosts ignore the header."""
        peer = (writer.get_extra_info("peername") or ("local",))[0]
        if self.public_origin:
            try:
                return str(ipaddress.ip_address(headers.get("x-real-ip", "")))
            except ValueError:
                return peer
        return peer

    def route(self, method: str, target: str, body: bytes, ip: str, admin: str = "") -> tuple[int, object]:
        url = urlsplit(target)
        path, query = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if path == "/dev/identity" and method == "POST":
                args = json.loads(body or b"{}")
                if not isinstance(args, dict):
                    raise ValueError("identity needs a JSON object with name, preset and public_key")
                if args.get("op") == "rejoin":
                    return 200, self.rejoin_identity(args)
                return 200, self.create_identity(str(args.get("name", "")), str(args.get("preset", "")), str(args.get("public_key", "")), sheet=args.get("sheet"), code=args.get("code"), look=args.get("look"))
            if path == "/snap/code" and method == "POST":
                return 200, self.issue_code(json.loads(body or b"{}"))
            if path.startswith("/snap/code/") and path.endswith("/log") and method == "GET":
                try:
                    return 200, self.code_log(path[len("/snap/code/"):-len("/log")])
                except ValueError as exc:
                    return 404, {"expired": True, "joined": False, "state": "expired", "error": str(exc)}
            if path.startswith("/snap/code/") and method == "GET":
                try:
                    row = self.code_status(path.rsplit("/", 1)[1])
                except ValueError:
                    return 404, {"expired": True, "joined": False, "state": "expired", "error": "ask the AI door for a new code"}
                return 200, {"joined": row["joined"], "expired": False, "state": "joined" if row["joined"] else "pending",
                             "fighter_id": row["claimed_by"] if row["joined"] else None, "name": row["name"],
                             "plan_stop_pct": row.get("plan_stop_pct")}
            if path == "/dev/shutdown" and self.public_origin:
                return 404, {"error": "not found"}  # hosted: the admin route does not exist
            if path == "/dev/shutdown" and method == "POST":
                if not hmac.compare_digest(admin, self.admin):
                    return 403, {"error": "needs the admin token printed at start"}
                self.stop = True
                return 200, {"stopping": True}
            if path == "/dev/corner" and method == "GET":
                return 200, self.corner(query.get("fighter", ""))
            if path == "/dev/speech" and method == "GET":
                return 200, self.speech_results.get(query.get("fighter_id"), {})
            if path == "/house/feed" and method == "GET":
                return 200, self.feed.public(int(query.get("since", "0")))
            if path == "/dev/why":
                return 200, self.why(query.get("segment_id", "segment:0"))
            if path == "/dev/players":
                return 200, self.players()
            if path == "/house/feed":  # the public feed, the roster projection and the predictions log
                return 200, self.feed.public(int(query.get("since", "0") or 0))
            if path == "/house/roster":
                return 200, self.house_roster()
            if path == "/house/record.jsonl":  # the public record (arena/predict.py), the JSONL file as written
                rec = self.round.arena.record
                return 200, (rec.path.read_bytes() if rec.path is not None and rec.path.exists() else b"", None)
            if path == "/house/leaderboards.json":  # most KOs and most correct predictions, per UTC day, top 5
                arena = self.round.arena
                now_ns = arena.server_time_ms() * 1_000_000
                day = query.get("day") or predict.utc_day(now_ns)
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
                    return 400, {"error": "day is YYYY-MM-DD (UTC)"}
                return 200, arena.record.leaderboards(day, now_ns=now_ns)
            if path == "/house/predictions.jsonl":
                log = getattr(self, "house_log", None)
                return 200, (self.house_predictions(), log.log_hash() if log is not None else None)
            if path == "/dev/terms":
                return 200, self.round.host.service.export_owner_state()["terms"]
            if path == "/dev/clock":
                return 200, {"now_ms": self.round.vnow(), "tick": self.round.arena.sim.state["tick"], "segment": self.round.arena.segment_id}
            if path in ("/", "/health", "/dev/health"):
                return 200, self.health()
            if path in ("/room/challenge", "/room/join"):
                self.start_hold()
            if (path == "/room/join" or path == "/room/control/frame") and method == "POST" and self.round.in_boundary() and self.guarded(path, body):
                return 200, {"type": "error", "code": "rate_limited", "request_id": None, "retry_after_ms": "200"}
            if path == "/room/control/open":
                return 200, self.round.arena.control.open_control(ip=ip)
            if path == "/room/control/frame":
                self.check_prediction_menu(body)
                reply = self.round.arena.control.frame(query["cid"], body)
                if isinstance(reply, dict) and reply.get("type") == "control_ready":
                    self.mark_paired(reply["nft_token_id"])
                if isinstance(reply, dict) and reply.get("state") == "accepted" and reply.get("prediction_lock"):
                    self.hold_until = 0.0
                return 200, reply
            if path == "/room/control/private":
                return 200, self.round.arena.control.drain_private(query["cid"])
            if path == "/room" or path.startswith("/room/"):
                reply = self.round.arena.control.request(method, target, body, ip=ip)
                if path == "/room/result" and isinstance(reply, dict) and reply.get("type") != "error":
                    self.round.result_served = True
                return 200, reply
            return 404, {"error": "not found"}
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return 400, {"error": str(exc)[:200]}

    async def handle(self, reader, writer) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        method, target, _ = (lines[0].split(" ") + ["", ""])[:3]
        headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:] if ":" in l)}
        key = headers.get("sec-websocket-key")
        if headers.get("upgrade", "").lower() == "websocket" and key:
            if urlsplit(target).path == '/room/live':
                allowed = self.own_hosts()
                origins = {ORIGIN, *(f'http://{host}' for host in allowed), *((self.public_origin,) if self.public_origin else ())}
                if headers.get('host') not in allowed or headers.get('origin') not in (None, *origins):
                    writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                    await writer.drain()
                    writer.close()
                    return
                await serve_live(self, reader, writer, key, ip=self.client_ip(writer, headers))
                return
            await self.spectate(reader, writer, key, "codec=1" in target, parse_qs(urlsplit(target).query).get("styles") == ["1"])
            return
        allowed_hosts = self.own_hosts()
        path = urlsplit(target).path
        try:
            if headers.get("host", "") not in allowed_hosts:  # DNS rebinding: only our own name and port
                status, value = 403, {"error": "host not allowed"}
            elif method not in ("GET", "POST"):
                status, value = 405, {"error": "GET or POST only"}
            elif method == "POST" and headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                status, value = 415, {"error": "POST bodies must be application/json"}  # a web page cannot send that cross-origin unpreflighted
            else:
                size = int(headers.get("content-length", "0"))
                if not 0 <= size <= 65536:
                    raise ValueError("body too large")
                body = await asyncio.wait_for(reader.readexactly(size), 5) if size else b""
                ip = self.client_ip(writer, headers)
                routed = self.route(method, target, body, ip, headers.get("x-dev-admin", ""))
                if inspect.isawaitable(routed):  # a host's slow route (near/chain/hosted_live.py) runs off this loop
                    routed = await routed
                status, value = routed
        except (ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            status, value = 400, {"error": str(exc)[:200]}
        ctype, extra = "application/json", ""
        if isinstance(value, tuple):  # the predictions log is served as the JSONL bytes on disk, with its hash
            (data, log_hash), ctype = value, "application/x-ndjson"
            extra = f"X-Log-Hash: {log_hash}\r\n" if log_hash else ""
        elif method == "GET" and path == "/SNAP.md" and status == 404:
            data = (ROOT / "near/SNAP.md").read_bytes()
            status, ctype = 200, "text/markdown; charset=utf-8"
        else:
            data = json.dumps(value, separators=(",", ":")).encode()
        paused = int(time.monotonic() < self.hold_until)
        cors = ""
        if method == "GET" and path in ("/dev/players", "/dev/health") and headers.get("origin") == ORIGIN:
            cors = f"Access-Control-Allow-Origin: {ORIGIN}\r\nVary: Origin\r\n"
        elif method == "GET" and path.startswith("/house/") and LOOPBACK_ORIGIN.fullmatch(headers.get("origin", "")):
            # the /house routes are public projections; any page served from this machine may read them
            cors = f"Access-Control-Allow-Origin: {headers['origin']}\r\nVary: Origin\r\n"
        writer.write(f"HTTP/1.1 {status} OK\r\nContent-Type: {ctype}\r\n{cors}{extra}"
                     f"X-Dev-Now: {self.round.vnow()}\r\nX-Dev-Paused: {paused}\r\n"
                     f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data)
        try:
            await writer.drain()
        except ConnectionError:
            pass
        writer.close()

    async def spectate(self, reader, writer, key: str, compact: bool = False, styles: bool = False) -> None:
        accept = base64.b64encode(hashlib.sha1(key.encode() + dev_brawl.GUID).digest())
        writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        if styles:
            self.styles.connect(writer)
            self.social_bytes = self.social_frame()
            writer.write(self.social_bytes)
            self.social_clients[writer] = self.social_bytes
        if compact:
            self.tables = codec.tables_for(self.round.arena.sim)
            self.client_tables[writer] = self.tables["table_id"]
            writer.write(dev_brawl.frame(codec.encode_tables(self.tables)))
            writer.write(dev_brawl.frame(codec.encode_tick(self.round.arena.sim, self.tables)))
        else:
            writer.write(dev_brawl.frame(self.latest))
        self.clients[writer] = compact
        try:
            while True:
                opcode, data = await dev_brawl.read_frame(reader)
                if opcode == 0x8:
                    writer.write(dev_brawl.frame(b"", 0x8))
                    break
                if opcode == 0x9:
                    writer.write(dev_brawl.frame(data, 0xA))
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            self.clients.pop(writer, None)
            self.styles.forget(writer)
            self.social_clients.pop(writer, None)
            self.client_tables.pop(writer, None)
            writer.close()

    def publish(self) -> None:
        for writer, peer in tuple(self.live_clients.items()):
            try:
                peer.publish()
            except (ConnectionError, ValueError):
                peer.close()
            if peer.closed:
                self.live_clients.pop(writer, None)
                writer.close()
        self.styles.refresh(self.round.arena.sim)
        self.social_bytes = self.social_frame()
        plain = dev_brawl.frame(self.latest)
        small = dev_brawl.frame(self.latest_codec) if self.latest_codec is not None else None
        tables = None
        for writer, compact in tuple(self.clients.items()):
            if writer.transport.get_write_buffer_size() > dev_brawl.MAX_BUFFER:
                self.dropped += 1
                continue
            self.styles.send(writer)
            if writer in self.social_clients and self.social_clients[writer] != self.social_bytes:
                writer.write(self.social_bytes)
                self.social_clients[writer] = self.social_bytes
            if compact and small is not None:
                if self.client_tables.get(writer) != self.tables["table_id"]:  # new roster, or a send this client missed
                    tables = tables or dev_brawl.frame(codec.encode_tables(self.tables))
                    writer.write(tables)
                    self.client_tables[writer] = self.tables["table_id"]
                writer.write(small)
            elif not compact:
                writer.write(plain)

    async def run_clock(self, ticks: int | None = None) -> None:
        period = 1 / RULES["tick_hz"]
        deadline = time.monotonic()
        count = 0
        while (ticks is None or count < ticks) and not self.stop:
            started = time.monotonic()
            if started < self.hold_until:
                await asyncio.sleep(0.02)
                deadline = time.monotonic()
                continue
            arena = self.round.arena
            try:
                arena.advance()
            except Exception as exc:  # a failed arena (e.g. seeds exhausted) is replaced, never hidden
                print(f"snap_local: arena stopped: {exc!r}", flush=True)
                traceback.print_exc()
                self.round.ever_dev = False
                for name in self.round.dev_members():
                    self.round.arena.members.pop(name, None)
                self.maybe_restart("the previous arena stopped")
                continue
            self.refresh_frames()
            self.slowest = max(self.slowest, time.monotonic() - started)
            self.publish()
            count += 1
            deadline += period
            if time.monotonic() - deadline > 2 * period:
                # Behind by more than two ticks (a slow handler, a busy machine): never run ticks back to back to
                # catch up. Room time is sim time, so the sim simply runs slower for a while.
                self.resyncs += 1
                deadline = time.monotonic()
            await asyncio.sleep(max(0, deadline - time.monotonic()))


async def serve(dev: DevRoom, ready=None, ticks: int | None = None) -> None:
    listener = await asyncio.start_server(dev.handle, dev.bind, dev.port)
    dev.port = listener.sockets[0].getsockname()[1]
    if ready is not None:
        ready(dev.port)
    async with listener:
        await dev.run_clock(ticks)


def new_run_dir(state: Path, keep: int = 4) -> Path:
    """A fresh <state>/runs/<UTC time> for this start's rounds; earlier runs beyond the newest `keep` are removed.
    Only directories this host made (runs/<YYYYmmddTHHMMSSZ>) are ever removed."""
    runs = state / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = re.compile(r"[0-9]{8}T[0-9]{6}Z(-[0-9]+)?")
    old = sorted(p for p in runs.iterdir() if p.is_dir() and not p.is_symlink() and stamp.fullmatch(p.name))
    for p in old[:max(0, len(old) - keep)]:
        shutil.rmtree(p)
    name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run, n = runs / name, 1
    while run.exists():
        run, n = runs / f"{name}-{n}", n + 1
    run.mkdir()
    return run


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--house", choices=("dev", "keyed", "live"), default="dev",
                    help="dev (default): the deterministic house, no key. keyed: no key, the house posts its labelled keyed "
                         "lines under the autopilot chip. live: the 14 personas on the NEAR AI Cloud model, "
                         "key from the NEARAI_API_KEY environment variable, under the daily budget caps")
    ap.add_argument("--budget", choices=["auto"] + sorted(house_runtime.DAY_CAPS_USD), default="auto",
                    help="the live house's cap period: auto follows the hackathon calendar (building $2, soak and judging $8, "
                         "after $3); a period name overrides it, and the roster says override")
    ap.add_argument("--bind", default="127.0.0.1",
                    help="the listen address (default loopback). Hosted in a container, 0.0.0.0 inside the container's "
                         "own network, published to the host's loopback only")
    ap.add_argument("--public-origin", default=None,
                    help="hosted behind nginx: https://<name>. Adds that name to the Host and Origin checks, takes the "
                         "client address from X-Real-IP, removes /dev/shutdown and never prints the admin token")
    ap.add_argument("--state-dir", default=None,
                    help="a persistent directory: the house's meter and logs live in <state>/house, and each start's "
                         "rounds in a fresh <state>/runs/<UTC time> (the 4 newest earlier runs are kept)")
    args = ap.parse_args()
    if args.state_dir is not None:
        if args.data_dir is not None:
            raise SystemExit("snap_local: --state-dir and --data-dir are exclusive")
        data_dir = str(new_run_dir(Path(args.state_dir)))
    else:
        data_dir = args.data_dir or tempfile.mkdtemp(prefix="snap-local-")
    try:
        dev = DevRoom(args.port, data_dir, house=args.house, budget_mode=args.budget,
                      public_origin=args.public_origin, state_dir=args.state_dir)
    except house_live.KeyMissing as exc:
        raise SystemExit(f"snap_local: {exc}")
    except ValueError as exc:
        raise SystemExit(f"snap_local: {exc}")
    dev.bind = args.bind
    if dev.feed.notice():
        print(f"snap_local: {dev.feed.notice()}: set TRENCHIE_BLOCKLIST to the block list kept outside the repo; "
              "until then every feed line is muted to an emote", flush=True)
    print(f"snap_local: house: {dev.house_kind} ({dev.house_model}"
          + (f", {dev.house_budget.mode} cap ${house_runtime.DAY_CAPS_USD[dev.house_budget.mode]}/day ({dev.house_budget.source}))" if args.house == "live" else ", no model calls)"), flush=True)
    if dev.public_origin:
        print(f"snap_local: DEV arena listening on {args.bind}:{args.port}, hosted as {dev.public_origin}; data {data_dir}, "
              f"house state {dev.house_parent / 'house'}. {MODE_NOTE} The admin route is off (hosted); "
              "stop it with SIGTERM.", flush=True)
    else:
        print(f"snap_local: DEV arena on http://127.0.0.1:{args.port} (spectator ws://127.0.0.1:{args.port}); "
              f"data {data_dir}. {MODE_NOTE} Stop it with Ctrl-C, or POST /dev/shutdown with header X-Dev-Admin: {dev.admin}", flush=True)
    try:
        asyncio.run(serve(dev))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
