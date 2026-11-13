"""Game composition root. The room service alone exposes validated control."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import unicodedata
from typing import TYPE_CHECKING, Protocol

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from . import predict, sim, replay as replay_engine
except ImportError:
    import predict
    import sim
    import replay as replay_engine

if TYPE_CHECKING:
    from room.slots import SlotStore
    from room.identity import IdentityAuthority
    from room.bridge import (SlotBinding, OwnerBinding, JoinRequest, SaleControlRequest,
                             SaleControlLookup, IdentityEvidence, ReservedLife, PredictionRequest,
                             PredictionLock, FighterBinding, PublicSnapshot, IntentRequest,
                             Receipt, ReleaseAck, SaleAction, SaleAcknowledgement, SealedRecord, Error,
                             GameBridge)


class ControlPort(Protocol):
    """Transport methods shared by local house, browser and native clients."""

    def request(self, method: str, target: str, body: bytes = b"", *, ip: str) -> dict: ...
    def open_control(self, *, ip: str, origin: str | None = None) -> dict: ...
    def frame(self, connection_id: str, body: bytes) -> dict: ...
    def close_control(self, connection_id: str) -> None: ...
    def drain_private(self, connection_id: str) -> list[dict]: ...
    def drain_snapshots(self, connection_id: str) -> list[dict]: ...


class RoomPort(ControlPort, Protocol):
    """Trusted service callbacks driven only by the authoritative host."""

    def maintain(self) -> None: ...
    def life_boundary(self, grant_id: str) -> dict | None: ...
    def publish_snapshot(self) -> None: ...


class RoomIngress:
    """Expose the bound validator without exporting host callbacks to clients."""

    def __init__(self, room: ControlPort):
        self.__room = room

    def request(self, method: str, target: str, body: bytes = b"", *, ip: str) -> dict:
        return self.__room.request(method, target, body, ip=ip)

    def open_control(self, *, ip: str, origin: str | None = None) -> dict:
        return self.__room.open_control(ip=ip, origin=origin)

    def frame(self, connection_id: str, body: bytes) -> dict:
        return self.__room.frame(connection_id, body)

    def close_control(self, connection_id: str) -> None:
        self.__room.close_control(connection_id)

    def drain_private(self, connection_id: str) -> list[dict]:
        return self.__room.drain_private(connection_id)

    def drain_snapshots(self, connection_id: str) -> list[dict]:
        return self.__room.drain_snapshots(connection_id)


def room_service_factory(slots: SlotStore, identity: IdentityAuthority,
                         **options: object) -> Callable[[GameBridge], RoomPort]:
    """Bind the installed service to game callbacks; absence is an import error."""
    from room.service import RoomService

    def bind(bridge: GameBridge) -> RoomPort:
        return RoomService(slots=slots, bridge=bridge, identity=identity, **options)

    return bind


def _control_json(value: object) -> str:
    """Canonical wire JSON uses lowercase Unicode escapes for every control."""
    if isinstance(value, str):
        text = '"' + ''.join('\\u%04x' % ord(c) if ord(c) < 32 else
            '\\' + c if c in ('"', '\\') else c for c in value) + '"'
        text.encode("utf-8", errors="strict")
        return text
    if value is None or type(value) in (bool, int):
        return json.dumps(value)
    if type(value) is list:
        return '[' + ','.join(_control_json(item) for item in value) + ']'
    if type(value) is dict and all(type(k) is str and k.isascii() for k in value):
        return '{' + ','.join(_control_json(k) + ':' + _control_json(value[k]) for k in sorted(value)) + '}'
    raise ValueError("control values require integer JSON and ASCII keys")


def control_digest(message: dict | None) -> str:
    """Commit the entire wire message excluding only its outer signature."""
    unsigned = None if message is None else {k: v for k, v in message.items() if k != "signature"}
    return hashlib.sha256(_control_json(unsigned).encode("utf-8")).hexdigest()


def copy_data(value):
    return json.loads(sim.canonical(value))


def error(code):
    return {"type": "error", "code": code, "request_id": None, "retry_after_ms": None}


def dev_prefixed(value) -> bool:
    """True when a name would read as a DEV trenchie: it starts with `dev-` after NFKC, casefolding, any
    Unicode dash read as `-`, and zero-width and control characters removed. (Look-alike letters from other
    scripts are not folded; the production gate also refuses anything the view would label DEV by id.)"""
    text = unicodedata.normalize("NFKC", str(value))
    text = "".join("-" if unicodedata.category(c) == "Pd" or c == "\u2212" else c
                   for c in text if unicodedata.category(c) not in ("Cf", "Cc"))
    return text.lstrip().casefold().startswith("dev-")


DEV_FIELDS = ("nft_token_id", "member_id", "slot_id", "grant_id", "session_key_id")


def edge_error(rules):
    """Held at a segment's last ticks: retry once the next segment has opened (a whole input delay)."""
    return {"type": "error", "code": "rate_limited", "request_id": None,
            "retry_after_ms": str(rules["input_delay"] * rules["milliseconds_per_second"] // rules["tick_hz"])}


def retire_fighter(game, name):
    game.state["fighters"].pop(name, None)
    game.state["inputs"] = [r for r in game.state["inputs"] if r["fighter_id"] != name]


engine_commitment = replay_engine.engine_commitment


class Store:
    """Only seeds, effective inputs, boundary state and sealed records persist."""

    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.segments = self.root / "segments"
        self.segments.mkdir(exist_ok=True)
        self.journal = self.root / "engine.jsonl"
        if self.segments.resolve().parent != self.root or self.journal.is_symlink():
            raise ValueError("storage paths must stay inside the data volume")
        self.index = 0
        self.previous = "0" * 64
        if self.journal.exists():
            with self.journal.open("rb") as stream:
                for line in stream:
                    if not line.endswith(b"\n"):
                        raise ValueError("incomplete journal; recovery required")
                    row = json.loads(line)
                    body = row["body"]
                    if row["previous"] != self.previous or row["hash"] != sim.digest([self.previous, body]):
                        raise ValueError("journal integrity failure")
                    self.previous = row["hash"]
                    self.index += 1

    def records(self):
        with self.journal.open("rb") as stream:
            for line in stream:
                yield json.loads(line)["body"]

    def append(self, kind, value):
        body = {"kind": kind, "value": copy_data(value)}
        fingerprint = sim.digest([self.previous, body])
        row = {"body": body, "previous": self.previous, "hash": fingerprint}
        with self.journal.open("ab") as stream:
            stream.write(sim.canonical(row) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        index = self.index
        self.index += 1
        self.previous = fingerprint
        return index

    def _segment_path(self, name):
        if not re.fullmatch(r"segment:(0|[1-9][0-9]{0,19})", name):
            raise ValueError("invalid segment id")
        return self.segments / (name.replace(":", "-") + ".json")

    def put_segment(self, name, record):
        path = self._segment_path(name)
        content = sim.canonical(record) + b"\n"
        if path.exists():
            if path.read_bytes() != content:
                raise ValueError("sealed segment is immutable")
            return
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def segment(self, name):
        return json.loads(self._segment_path(name).read_bytes())


def encode_snapshot(game):
    """A full visible map, encoded once as id tables plus compact integer arrays."""
    state, rules = game.state, game.rules
    names = sim.ordered_ids(state["fighters"])
    rows = sim.ordered_ids(rules["items"])
    name_index = {name: index for index, name in enumerate(names)}
    row_index = {name: index for index, name in enumerate(rows)}
    statuses = {"alive": 0, "bench": 1, "left": 2}
    fighters, casts = [], []
    for name in names:
        f = state["fighters"][name]
        fighters.append([name_index[name], f["x"], f["y"], f["hp"], f["direction"], statuses[f["state"]],
                         name_index.get(f["target"], -1), max(0, f["sig_at"] - state["tick"]),
                         [row_index[f["equipped"][slot]] for slot in sorted(f["equipped"])], f["shield"]])
        if f["cast"] is not None:
            cast = f["cast"]
            casts.append([name_index[name], sorted(rules["signatures"]).index(cast["kind"]),
                          cast["resolve_at"], cast["x"], cast["y"]])
    drops = [[key, row_index[state["drops"][key]["row"]], state["drops"][key]["x"],
              state["drops"][key]["y"], state["drops"][key]["expires_at"]]
             for key in sim.ordered_ids(state["drops"])]
    objects = [[key, obj["kind"], obj["x"], obj["y"], obj["resolve_at"],
                obj.get("target_x", obj["x"]), obj.get("target_y", obj["y"]),
                obj.get("vx", 0), obj.get("vy", 0), obj["range"], obj["angle"],
                obj.get("until", obj["resolve_at"]), obj.get("radius", 0), obj.get("width", 0)]
               for key in sim.ordered_ids(state["objects"]) for obj in [state["objects"][key]]]
    return sim.canonical([rules.get("snapshot_version", 1), state["tick"], names, rows, fighters, drops,
                          objects, casts, state["events"]])


def replay_segment(record, rules=None, frame_sink=None):
    return replay_engine.replay_segment(record, rules, frame_sink, encode_snapshot)


class Arena:
    def __init__(self, context, seeds, *, data_dir="/srv/arena/data",
                 room_factory: Callable[[GameBridge], RoomPort] | None = None,
                 profile_provider=None, identity_resolver=None, receipt_signer=None,
                 admission_gate=None, life_guard=None, pick_resolver=None, sale_adapter=None,
                 house_runtime=None, server_time_ms=None, rules=sim.DEFAULT_RULES, recover=False, dev_host=None,
                 prediction_log=None, chain=None, record=None, room_snapshots=True):
        self.context = copy_data(context)
        # Push the room's public snapshot to its control connections every tick (room.publish_snapshot), for a
        # transport that delivers them through drain_snapshots. The push projects, canonicalises and schema-validates
        # the whole snapshot each tick, so a host whose transport never drains pushed snapshots turns it off
        # (snap_local). An explicit observe still projects and validates on demand; the sim and the spectator frames
        # are the same either way.
        self.room_snapshots = bool(room_snapshots)
        if self.context.get("rules_hash") != sim.digest(rules):
            raise ValueError("context rules hash mismatch")
        if rules["tick_hz"] != 20 or rules["segment_ticks"] != 1200:
            raise ValueError("room clock requires 20 Hz and 1200 ticks per segment")
        # A chain writer (near/chain) replaces the given seeds with its committed, unused ones, in commit order.
        self.chain = chain
        if chain is not None and recover:
            raise ValueError("a chain-attached arena does not recover a journal: start a fresh arena (an interrupted "
                             "segment is never settled); the chain writer resumes from its own state")
        if chain is not None:
            seeds = chain.claim_seeds(self)
        if not seeds:
            raise ValueError("published seeds are required")
        # Only a DEV host (the local snap-in host) may seat a `dev-` id. A host says so with dev_host=True; left
        # unset, it follows the deployment id (`dev-...`), which an operator sets and a player cannot reach.
        self.dev_host = (str(self.context.get("deployment_id", "")).startswith("dev-")
                         if dev_host is None else bool(dev_host))
        self.refusals = deque(maxlen=100)
        self.seeds = tuple(seeds)
        for seed in seeds:
            sim.SplitMix64(seed, rules)
        self.sim = sim.Sim(seeds[0], rules)
        self.store = Store(data_dir)
        if self.store.index and not recover:
            raise ValueError("existing journal requires explicit recovery")
        self.profile_provider = profile_provider
        self.identity_resolver = identity_resolver
        self.receipt_signer = receipt_signer
        self.admission_gate = admission_gate or (lambda: False)
        self.life_guard = life_guard or (lambda b: False)
        if chain is not None:      # a chain token's owner is re-read from chain before each new life
            guard = self.life_guard
            self.life_guard = lambda b: guard(b) and chain.owner_ok(b)
        self.pick_resolver = pick_resolver
        self.sale_adapter = sale_adapter
        self.house_runtime = house_runtime
        # The public per-AI predictions log (F79, house/predictions.py). At each seal its log_hash() is journalled
        # beside the segment (the sealed record itself is unchanged), for the batch writer to carry.
        self.prediction_log = prediction_log
        self.prediction_log_hashes = {}
        self.prediction_log_refusals = deque(maxlen=100)
        self.server_time_ms = server_time_ms or (lambda: time.time_ns() // (rules["nanoseconds_per_second"] // rules["milliseconds_per_second"]))
        # The public record (arena/predict.py): a seal row per completed life; the chain writer adds settlement rows.
        # A host passes its one record (a file under its persistent state dir) to every round's arena; alone, an arena
        # keeps its rows in memory, never in the store (replay data only). `record_run` names this arena in the rows: its deployment and its first published
        # seed, which differ between arenas (life ids restart in each) and are the same after a journal recovery, so
        # nothing more is stored (the store keeps only seeds, inputs, boundary state and sealed records).
        self.record = record if record is not None else predict.Record(None)
        self.record_run = f"{self.context.get('deployment_id', 'arena')}@{self.seeds[0]}"
        self.sealed_rows = {}
        self.members = {}
        self.inventories = {}
        self.locks = {}
        self.receipts = {}
        self.segment_index = 0
        self.segment_start = 0
        self.sequence = 0
        self.journal_tick = 0
        self.ordinal = 0
        self.commands = []
        self.input_events = []
        self.completed_lives = []
        # life id -> house or not, noted when the life ends: by the seal a trenchie that swam home is no longer a
        # member or a fighter, and its record row still needs it (seal-house-flag)
        self.life_house = {}
        self.deferred, self.deferred_seq = [], 0     # engine effects held across a segment seal (see at_edge)
        self.initial_state = self.sim.export()
        self.serialisations = 0
        self.dropped_sends = 0
        self.dropped_ticks = 0
        self.deadlines = deque(maxlen=rules["metrics_samples"])
        self.tick_times_ns = deque(maxlen=rules["metrics_samples"])
        self.fanout = replay_engine.Fanout(rules["snapshot_queue"])
        self.subscribers = self.fanout.subscribers
        self.replays = replay_engine.Replays(self.store.segment, encode_snapshot,
                                             rules["replay_workers"], rules["replay_cache"])
        self.replay_slots = self.replays.slots
        self.replay_cache = self.replays.cache
        self.failed = False
        self.bridge = ArenaBridge(self)
        self.room = room_factory(self.bridge) if room_factory is not None else None
        self.control = RoomIngress(self.room) if self.room is not None else None
        if recover:
            self._recover()
        else:
            self.store.append("initial", {"state": self.initial_state, "seeds": list(self.seeds)})
        self.snapshot_bytes = encode_snapshot(self.sim)
        self.fanout.latest = self.snapshot_bytes
        self.serialisations += 1

    @property
    def segment_id(self):
        return "segment:" + str(self.segment_index)

    def at_edge(self):
        """True on the last input_delay ticks of a segment.

        An input enqueued now applies at tick + input_delay, which is already the next segment, but this
        segment's record would journal it, and the sealed record would then hold an input at or after its
        own last tick (portable_records refuses such a segment). So the engine effect (the enqueue and its
        public row) is held and runs on the next segment's first tick, recorded in that segment. The room
        sees its bookkeeping change at once and never an error, except an intent, whose receipt names the
        applied tick: that one is held with rate_limited and re-sent by the client.
        """
        r = self.sim.rules
        return r["segment_ticks"] - r["input_delay"] <= self.sim.state["tick"] - self.segment_start < r["segment_ticks"]

    def dev_label_field(self, binding, profile):
        """The first identity field that would wear the DEV label on a production host, else None.

        A refusal is logged by field only (never the value) in `refusals` and shown by health(); the wire
        answer is `banned`. A DEV host seats `dev-` ids by design.
        """
        if self.dev_host:
            return None
        for field in DEV_FIELDS:
            if dev_prefixed(binding.get(field, "")):
                break
        else:
            field = "public_name" if dev_prefixed(profile.get("public_name", "")) else None
        if field is not None:
            self.refusals.append({"tick": self.sim.state["tick"], "field": field, "reason": "dev_prefix"})
        return field

    def _boundary_start(self):
        """The tick an input held now will apply at: the next segment's first tick plus the input delay."""
        r = self.sim.rules
        return self.segment_start + r["segment_ticks"] + r["input_delay"]

    def _op(self, entry):
        """Run or hold one engine effect. Returns the apply tick as a string."""
        if self.at_edge():
            entry = dict(entry, id=self.deferred_seq, segment=self.segment_index)
            self.deferred_seq += 1
            self._record("deferred", entry)
            self.deferred.append(entry)
            return str(self._boundary_start())
        return str(self._run_op(entry).tick)

    def _run_op(self, e):
        name, op = e["name"], e["op"]
        if op == "join":
            row = self._enqueue("join", name, e["payload"])
            self._public_event("join", name, e["life_id"], self.bridge._public_fighter(name, None), row.tick)
        elif op == "loadout":
            row = self._enqueue("loadout", name, e["payload"])
        elif op == "spawn":
            row = self._enqueue("spawn", name, {"life_id": e["life_id"]})
            self._public_event("life_start", name, e["life_id"], e["lock"], row.tick)
        elif op == "leave":
            # Leave sorts before loadout at the same apply tick. A released
            # activation must drop its equipment command before it closes bench.
            if any(row["kind"] == "loadout" and row["fighter_id"] == name for row in self.sim.state["inputs"]):
                self._record("cancel_loadout", name)
                replay_engine.cancel_loadouts(self.sim, name)
            self._record("cancel_spawn", name)
            replay_engine.cancel_spawns(self.sim, name)
            row = self._enqueue("leave", name, {})
            self._public_event("leave", name, e["life_id"], {"reason": "leave"})
        else:
            raise ValueError("unknown held effect")
        return row

    def _flush_deferred(self):
        """First thing in a new segment: run what the last two ticks of the old one held, in order."""
        while self.deferred:
            e = self.deferred[0]
            if e["name"] in self.members:
                row = self._run_op(e)
                if e["op"] == "spawn" and str(row.tick) != e["start_tick"]:
                    self.failed = True
                    raise RuntimeError("held spawn applied at a different tick than announced")
            self.deferred.pop(0)
            self._record("flushed", {"id": e["id"]})

    def can_admit(self):
        return (not self.failed and self.room is not None and self.profile_provider is not None
                and self.identity_resolver is not None and self.receipt_signer is not None
                and bool(self.admission_gate()))

    def _record(self, kind, value):
        try:
            self._flush_ticks()
            index = self.store.append(kind, value)
        except Exception:
            self.failed = True
            raise
        if kind in ("input", "advance", "retire", "cancel_spawn", "cancel_loadout"):
            self.commands.append({"kind": kind, "value": copy_data(value)})
        return index

    def _flush_ticks(self):
        current = self.sim.state["tick"]
        if current > self.journal_tick:
            try:
                self.store.append("advance", current - self.journal_tick)
            except Exception:
                self.failed = True
                raise
            self.journal_tick = current

    def _member_changed(self, name):
        self._record("member", {"name": name, "member": self.members.get(name)})

    def _fighter_event(self, name, kind, text):
        """A display-only line for the fighter's own panel (the host's log); never an engine input."""
        sink = getattr(self, "fighter_event", None)
        if sink is not None:
            sink(name, kind, text)

    def _life_deadline(self, member):
        window = self.sim.rules["prediction_window_ticks"]
        member["deadline_tick"] = self.sim.state["tick"] + window
        member["deadline_ms"] = self.server_time_ms() + window * self.sim.rules["milliseconds_per_second"] // self.sim.rules["tick_hz"]

    def _enqueue(self, kind, name, payload):
        row = sim.Input(self.sim.state["tick"] + self.sim.rules["input_delay"], kind, name,
                        self.sequence, payload)
        before = self.sim.export()
        try:
            self.sim.enqueue(row)
            self._record("input", row.record())
        except Exception:
            self.sim = sim.Sim.restore(before, self.sim.rules)
            raise
        self.sequence += 1
        return row

    def _public_event(self, kind, name, life, payload, tick=None):
        member = self.members[name]
        value = {"index": str(len(self.input_events)),
                 "tick": str(self.sim.state["tick"] if tick is None else tick), "kind": kind,
                 "fighter_id": name, "nft_token_id": member["binding"]["nft_token_id"],
                 "life_id": life, "payload": payload}
        value["record_hash"] = sim.digest(value)
        self.input_events.append(value)
        self._record("public_event", value)

    def _ring_load(self):
        return len(self.sim._live()) + sum(m["spawn_pending"] for m in self.members.values())

    def _retire(self, name):
        m = self.members[name]
        f = self.sim.state["fighters"].get(name)
        if f is not None:
            inventory = {"owner": m["binding"]["account_id"], "bag": copy_data(f["bag"]),
                         "life_number": m["life_number"]}
            self._record("inventory", {"name": name, "inventory": inventory})
            self.inventories[name] = inventory
        self._record("retire", name)
        retire_fighter(self.sim, name)
        self.members.pop(name, None)
        self._member_changed(name)

    def _schedule(self):
        tick, r = self.sim.state["tick"], self.sim.rules
        for name in sorted(list(self.members)):
            f = self.sim.state["fighters"].get(name)
            if f is not None and f["state"] == "left":
                self._retire(name)
        outside = sum(not m["profile"]["house"] for m in self.members.values())
        desired_house = max(r["house_min"], r["house_fill"] - outside)
        houses = sum(m["profile"]["house"] for m in self.members.values())
        for name in sorted(list(self.members), key=lambda n: self.members[n]["queue_order"]):
            m = self.members[name]
            f = self.sim.state["fighters"].get(name)
            if m["profile"]["house"] and houses > desired_house and f is not None and f["state"] == "bench" and not m["spawn_pending"]:
                self._retire(name)
                houses -= 1
        if self.house_runtime is not None:
            self.house_runtime.poll(self.control, tick, tuple(sorted(self.sim.rules["house"])),
                                    max(0, desired_house - houses), self.bridge.observe(None))
        for name in sorted(list(self.members), key=lambda n: self.members[n]["queue_order"]):
            m = self.members[name]
            f = self.sim.state["fighters"].get(name)
            if m["released"] or m["spawn_pending"]:
                continue
            if f is None or f["state"] != "bench":
                continue
            if m.get("bench_hold") and m["ever_started"]:
                # Q5: the player keeps this trenchie on the bench; the 45 s timer is stopped until it is sent back in
                if m.get("held_since") is None:
                    m["held_since"] = tick
                    self._member_changed(name)
                    self._fighter_event(name, "held", "On the bench, held. The 45 s timer is stopped.")
                continue
            if self._ring_load() >= r["ring_max"]:
                continue
            if m["ever_started"] and (tick >= f["respawn_at"] + m.get("held_ticks", 0) or self._ring_load() < r["ring_min"]):
                if not m["awaiting_life"]:
                    m["life_number"] += 1
                    m["life_id"] = name + ":life:" + str(m["life_number"])
                    m["awaiting_life"] = True
                    m["activation_requested"] = True
                    self._life_deadline(m)
                    self._member_changed(name)
                if m["life_id"] not in self.locks:
                    if tick >= m["deadline_tick"]:
                        self.bridge.lock_prediction(m["binding"], m["life_id"], None)
                        m["activation_requested"] = True
            if m["activation_requested"] and m["life_id"] in self.locks:
                lock = self.locks[m["life_id"]]["lock"]
                self.bridge.activate(m["binding"], m["life_id"], lock["lock_ref"])

    def _log_key(self, life_id):
        """A life's key in a predictions log that outlives this arena: life ids restart at :life:0 in every arena, and
        `record_run` (deployment and first seed) differs between arenas and host starts but not across a journal
        recovery, so a recovered life is still refused and a restarted host's lives are not."""
        return self.record_run + "/" + life_id

    def _log_player_lock(self, m, life_id, pick):
        """F79 for a player's AI: its lock (or explicit no-prediction) goes in the public log. A house life is logged
        by the house driver. A spread that is not whole percents is logged as no prediction, never rounded."""
        if self.prediction_log is None or m["profile"]["house"]:
            return
        spread = zero = None
        if pick is not None:
            bps = pick["payload"]["spread_bps"]
            values = [bps.get(k, 0) for k in ("one", "two", "three", "four_plus")] + [pick["payload"]["zero_bps"]]
            if all(v % 100 == 0 for v in values):
                spread, zero = [v // 100 for v in values[:4]], values[4] // 100
        try:
            self.prediction_log.lock(self._log_key(life_id), self.sim.rules_hash, m["binding"]["nft_token_id"],
                                     m["binding"]["account_id"], m["profile"]["model"], spread, zero)
        except ValueError as exc:                       # an already-sealed life after recovery: the log keeps the first
            self.prediction_log_refusals.append({"life_id": life_id, "reason": str(exc)[:120]})

    def _log_player_end(self, m, life_id, kos):
        if self.prediction_log is None or m["profile"]["house"]:
            return
        entry = self.prediction_log.locks.get(self._log_key(life_id))
        if entry is not None and not entry["resolved"]:
            self.prediction_log.resolve(self._log_key(life_id), kos)

    def _collect_events(self) -> list[str]:
        """Record the whole tick before returning grants to notify externally."""
        boundaries = []
        for event in self.sim.state["events"]:
            name = event.get("fighter")
            if name not in self.members:
                continue
            m = self.members[name]
            if event["kind"] == "respawn":
                m["spawn_pending"] = False
                m["ever_started"] = True
                m["awaiting_life"] = False
                m["held_ticks"], m["held_since"] = 0, None
                self._member_changed(name)
            if event["kind"] in ("ko", "leave"):
                if self.chain is not None:
                    self.chain.life_ended(name)
                lock = self.locks.get(m["life_id"])
                if lock is not None:
                    f = self.sim.state["fighters"][name]
                    record = {"life_id": m["life_id"], "nft_token_id": name,
                              "prediction_lock": lock["lock"], "ko_count": str(f["life_kos"]),
                              "inventory_hash": sim.digest(f["bag"]), "completed": True}
                    self.completed_lives.append(record)
                    self.life_house[record["life_id"]] = bool(m["profile"]["house"])
                    self._record("life_end", record)
                    self._log_player_end(m, m["life_id"], f["life_kos"])
                if event["kind"] == "ko":
                    m["life_number"] += 1
                    m["life_id"] = name + ":life:" + str(m["life_number"])
                    m["awaiting_life"] = True
                    m["activation_requested"] = False
                    m["activation"] = None
                    m["queue_order"] = self.ordinal
                    self.ordinal += 1
                    m["profile"]["bag"] = copy_data(self.sim.state["fighters"][name]["bag"])
                    self._life_deadline(m)
                    self._member_changed(name)
                    if self.room is not None and not m["released"]:
                        boundaries.append(m["binding"]["grant_id"])
        return boundaries

    def advance(self, ticks=1):
        sim.unsigned(ticks, "ticks")
        for _ in range(ticks):
            try:
                self._advance_tick()
            except Exception:
                self.failed = True
                raise

    def _prepare_segment(self) -> None:
        """Open the next segment before any mutation of a completed boundary."""
        if self.failed:
            raise RuntimeError("engine is paused")
        if self.sim.state["tick"] - self.segment_start == self.sim.rules["segment_ticks"]:
            self._seal()
            self._open_next_segment()

    def _advance_tick(self) -> None:
        self._prepare_segment()
        if self.room is not None:
            self.room.maintain()
        self._schedule()
        self.sim.step()
        self.commands.append({"kind": "advance", "value": 1})
        boundaries = self._collect_events()
        if self.sim.state["tick"] % self.sim.rules["tick_hz"] == 0:
            self._flush_ticks()
        self.snapshot_bytes = encode_snapshot(self.sim)
        self.serialisations += 1
        self.fanout.publish(self.snapshot_bytes)
        if self.room is not None and self.room_snapshots:
            self.room.publish_snapshot()
        self.dropped_sends = self.fanout.dropped
        if self.sim.state["tick"] - self.segment_start == self.sim.rules["segment_ticks"]:
            self._seal()
        # A notification can synchronously reserve a life and open the next segment.
        # It must see every completed life and the durable seal for this tick first.
        for grant_id in boundaries:
            self.room.life_boundary(grant_id)

    def _seal(self):
        self._flush_ticks()
        lives = copy_data(self.completed_lives)
        held = {e["name"] for e in self.deferred if e["op"] == "join"}      # their join runs in the next segment
        names = sorted(({m["binding"]["nft_token_id"] for m in self.members.values()} - held)
                       | {life["nft_token_id"] for life in lives})
        predictions = [self.locks[key]["public"] for key in sorted(self.locks)]
        sealed = {"segment_id": self.segment_id, "life_ids": sorted(life["life_id"] for life in lives),
                  "nft_token_ids": names, "inputs_hash": sim.digest(self.input_events),
                  "seed_hash": sim.digest(str(self.sim.state["seed"])), "rules_hash": self.sim.rules_hash,
                  "final_state_hash": self.sim.state_hash(), "predictions_log_hash": sim.digest(predictions),
                  "completed": True, "tick_count": str(self.sim.rules["segment_ticks"]), "lives": lives,
                  "seed": str(self.sim.state["seed"]), "input_events": copy_data(self.input_events)}
        record = {"rules_hash": self.sim.rules_hash, "initial_state": self.initial_state,
                  "commands": self.commands, "sealed": sealed, "predictions": predictions}
        sealed["sealed_result_hash"] = engine_commitment(record)
        try:
            self.store.put_segment(self.segment_id, record)
        except Exception:
            self.failed = True
            raise
        if self.prediction_log is not None and self.prediction_log_hashes.get(self.segment_id) != self.prediction_log.log_hash():
            log_hash = self.prediction_log.log_hash()      # a re-seal of the same segment journals only a changed hash
            self._record("house_predictions", {"segment_id": self.segment_id, "log_hash": log_hash})
            self.prediction_log_hashes[self.segment_id] = log_hash
        self.sealed_rows = self._seal_rows(lives)
        if self.chain is not None:
            self.chain.sealed(self, self.segment_id, record)

    def _base_rate_at(self, at_ms):
        """The five-bin base rate a prediction locked at `at_ms` is rewarded at: the chain writer's last resolve
        before it, else the lab table (an arena with no chain, or before the first resolve)."""
        reader = getattr(self.chain, "base_rate_at", None)
        return list(reader(at_ms)) if reader is not None and at_ms is not None else list(predict.LAB_BASE_BPS)

    def _seal_rows(self, lives):
        """The public record's seal row for each life completed in this segment, {life_id: row as first written}."""
        rules, rows = self.sim.rules, {}
        now_ns = self.server_time_ms() * (rules["nanoseconds_per_second"] // rules["milliseconds_per_second"])
        for life in lives:
            token, life_id = life["nft_token_id"], life["life_id"]
            m, f = self.members.get(token), self.sim.state["fighters"].get(token)
            house = self.life_house.get(life_id)
            if house is None:
                house = m["profile"]["house"] if m is not None else bool(f is not None and f.get("house"))
            lock = self.locks.get(life_id)
            pick = (lock["public"].get("pick") if lock is not None else None)
            level, note = (predict.read_level(rules, pick["payload"]["spread_bps"], pick["payload"]["zero_bps"])
                           if pick is not None else (None, None))
            base = self._base_rate_at(lock.get("at_ms") if lock is not None else None)
            name = (m["profile"].get("public_name") if m is not None else None) or token
            self.record.add(predict.seal_row(life_id=life_id, persona=token, house=house, rules=rules, level=level,
                                             note=note, kos=life["ko_count"], base_bps=base, sealed_ns=now_ns,
                                             run=self.record_run, name=name))
            rows[life_id] = self.record.life(self.record_run, life_id)
        return rows

    def _open_next_segment(self):
        next_index = self.segment_index + 1
        if self.chain is not None:
            new = self.chain.take_seeds(self)
            if new:
                self.add_published_seeds(new)
        if next_index >= len(self.seeds):
            self.failed = True
            raise RuntimeError("published seed batch exhausted; admission closed")
        self.segment_index = next_index
        self.segment_start = self.sim.state["tick"]
        seed = self.seeds[next_index]
        self.sim.rng = sim.SplitMix64(seed, self.sim.rules)
        self.sim.state["seed"] = seed
        self.sim.state["rng"] = seed
        pending = {sim.canonical([row["kind"], row["fighter_id"], row["sequence"]]).decode("utf-8")
                   for row in self.sim.state["inputs"]}
        self.sim.state["seen"] = {key: self.sim.state["seen"][key] for key in sorted(pending)}
        self.initial_state = self.sim.export()
        self.commands, self.input_events, self.completed_lives = [], [], []
        self.life_house = {}
        self.receipts = {}
        active_lives = {m["life_id"] for m in self.members.values()}
        self.locks = {k: self.locks[k] for k in sorted(self.locks) if k in active_lives}
        self._record("open", {"segment_index": next_index, "state": self.initial_state})
        self._flush_deferred()

    def add_published_seeds(self, seeds):
        """Called by the game seed publisher after its commit, never room control."""
        batch = tuple(seeds)
        if not batch:
            raise ValueError("seed batch is empty")
        for seed in batch:
            sim.SplitMix64(seed, self.sim.rules)
        self._record("seeds", {"from_index": len(self.seeds), "seeds": list(batch)})
        self.seeds += batch

    def _recover(self):
        for entry in self.store.records():
            kind, value = entry["kind"], entry["value"]
            if kind == "initial":
                if tuple(value["seeds"]) != self.seeds:
                    raise ValueError("published seeds changed during recovery")
                self.sim = sim.Sim.restore(value["state"], self.sim.rules)
                self.initial_state = self.sim.export()
            elif kind == "member":
                if value["member"] is None:
                    self.members.pop(value["name"], None)
                else:
                    self.members[value["name"]] = value["member"]
                    self.ordinal = max(self.ordinal, value["member"]["ordinal"] + 1,
                                       value["member"]["queue_order"] + 1)
            elif kind == "deferred":
                self.deferred.append(value)
                self.deferred_seq = max(self.deferred_seq, value["id"] + 1)
            elif kind == "flushed":
                self.deferred = [e for e in self.deferred if e["id"] != value["id"]]
            elif kind == "inventory":
                self.inventories[value["name"]] = value["inventory"]
            elif kind == "seeds":
                if value["from_index"] != len(self.seeds):
                    raise ValueError("seed batch order changed")
                self.seeds += tuple(value["seeds"])
            elif kind == "lock":
                self.locks[value["lock"]["life_id"]] = value
            elif kind == "receipt":
                self.receipts[value["key"]] = value
            elif kind == "public_event":
                self.input_events.append(value)
            elif kind == "life_end":
                self.completed_lives.append(value)
                m = self.members.get(value["nft_token_id"])      # the journal retires it later, if at all
                if m is not None:
                    self.life_house[value["life_id"]] = bool(m["profile"]["house"])
            elif kind == "open":
                if self.sim.state["tick"] - self.segment_start == self.sim.rules["segment_ticks"]:
                    self.journal_tick = self.sim.state["tick"]
                    self._seal()
                self.sim = sim.Sim.restore(value["state"], self.sim.rules)
                self.segment_index = value["segment_index"]
                self.segment_start = self.sim.state["tick"]
                self.initial_state = self.sim.export()
                self.commands, self.input_events, self.completed_lives = [], [], []
                self.life_house = {}
                self.receipts = {}
                active_lives = {m["life_id"] for m in self.members.values()}
                self.locks = {k: self.locks[k] for k in sorted(self.locks) if k in active_lives}
            elif kind == "house_predictions":
                self.prediction_log_hashes[value["segment_id"]] = value["log_hash"]
            elif kind in ("input", "advance", "retire", "cancel_spawn", "cancel_loadout"):
                if kind != "advance":
                    self.commands.append(entry)
                if kind == "input":
                    self.sim.enqueue(sim.Input(**value))
                    self.sequence = max(self.sequence, value["sequence"] + 1)
                elif kind == "advance":
                    for _ in range(value or 1):
                        self.sim.step()
                        self.commands.append({"kind": "advance", "value": 1})
                elif kind == "cancel_spawn":
                    replay_engine.cancel_spawns(self.sim, value)
                elif kind == "cancel_loadout":
                    replay_engine.cancel_loadouts(self.sim, value)
                else:
                    retire_fighter(self.sim, value)
        self.journal_tick = self.sim.state["tick"]
        if self.sim.state["tick"] - self.segment_start == self.sim.rules["segment_ticks"]:
            self._seal()
        if self.deferred and self.deferred[0]["segment"] < self.segment_index:
            self._flush_deferred()      # a crash between the next segment's open record and its first effects

    def subscribe(self):
        return self.fanout.subscribe()

    def unsubscribe(self, queue):
        self.fanout.unsubscribe(queue)

    async def run(self, *, max_ticks=None, now_ns=time.monotonic_ns, sleep=asyncio.sleep):
        epoch = now_ns()
        step_ns = self.sim.rules["nanoseconds_per_second"] // self.sim.rules["tick_hz"]
        count = 0
        while max_ticks is None or count < max_ticks:
            deadline = epoch + (count + 1) * step_ns
            self.deadlines.append(deadline)
            delay = max(0, deadline - now_ns())
            await sleep(delay / self.sim.rules["nanoseconds_per_second"])
            before = now_ns()
            self.advance()
            self.tick_times_ns.append(max(0, now_ns() - before))
            count += 1

    async def serve(self, transport, *, port):
        if not self.can_admit():
            raise RuntimeError("room service and launch configuration required; admission closed")
        clock_task = asyncio.create_task(self.run())
        transport_task = asyncio.create_task(transport(
            host="127.0.0.1", port=port, compression=None, room=self.control,
            subscribe=self.subscribe, unsubscribe=self.unsubscribe, snapshot=lambda: self.snapshot_bytes,
            replay=self.open_replay, health=self.health))
        try:
            done, _ = await asyncio.wait((clock_task, transport_task), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            clock_task.cancel()
            transport_task.cancel()
            await asyncio.gather(clock_task, transport_task, return_exceptions=True)

    async def replay(self, segment_id):
        return await self.replays.frames(segment_id)

    async def open_replay(self, segment_id: str) -> replay_engine.Playback:
        """Return an isolated subscriber channel; callers drive and cancel playback."""
        frames = await self.replay(segment_id)
        return replay_engine.Playback(self.replays, segment_id, self.sim.rules["snapshot_queue"], frames[0])

    def health(self) -> dict:
        """The transport exposes this projection at its health route."""
        try:
            free = shutil.disk_usage(self.store.root).free
        except OSError:
            free = None
        return {"status": "unknown" if free is None else "red" if free < 2_000_000_000 else "amber" if free < 5_000_000_000 else "green",
                "free_disk_bytes": free, "tick": self.sim.state["tick"], "failed": self.failed,
                "dev_host": self.dev_host, "dev_prefix_refusals": len(self.refusals),
                **({"chain": self.chain.health()} if self.chain is not None else {})}


class ArenaBridge:
    """Structural implementation of the copied room's game interface."""

    def __init__(self, arena):
        self.arena = arena

    def _member(self, binding):
        a = self.arena
        if binding.get("context") != a.context:
            return None
        m = a.members.get(binding.get("nft_token_id"))
        if m is None or m["binding"] != binding:
            return None
        return m

    def resolve_identity(self, proof: JoinRequest | SaleControlRequest | SaleControlLookup) -> IdentityEvidence | Error:
        a = self.arena
        if a.identity_resolver is None:
            return error("ownership_unavailable")
        result = a.identity_resolver(proof)
        if not result or result.get("play_status") == "unknown":
            return error("ownership_unavailable")
        return copy_data(result)

    def reserve_life(self, slot_binding: SlotBinding) -> ReservedLife | Error:
        a = self.arena
        if not a.can_admit():
            return error("admission_closed")
        a._prepare_segment()
        b = copy_data(slot_binding)
        if b.get("context") != a.context:
            return error("context_mismatch")
        name = b["nft_token_id"]
        m = a.members.get(name)
        if m is not None:
            if m["released"]:
                return error("stale_slot")
            old = m["binding"]
            if b != old:
                immutable = ("nft_token_id", "account_id", "persona_digest", "slot_id", "member_id")
                if any(b[k] != old[k] for k in immutable) or int(b["generation"]) <= int(old["generation"]):
                    return error("stale_slot")
                m["binding"] = b
                a._member_changed(name)
            return {"binding": b, "life_id": m["life_id"],
                    "prediction_deadline": str(m["deadline_ms"])}
        if len(a.members) >= a.sim.rules["capacity"]:
            return error("room_full")
        # A released member keeps its entry until its fighter has swum home (retired at "left"), but the room has
        # already freed its slot and may hand that slot id to the next joiner: only a member still holding it clashes.
        if any(not m["released"] and m["binding"]["slot_id"] == b["slot_id"] for m in a.members.values()):
            return error("stale_slot")
        supplied = a.profile_provider(b)
        fields = ("house", "public_name", "model", "style", "loadout", "bag")
        profile = copy_data({k: supplied[k] for k in fields})
        reserved_label = a.dev_label_field(b, profile)
        if reserved_label is not None:
            return error("banned")
        if profile["house"]:
            profile["house_spend_microusd"] = supplied.get("house_spend_microusd", 0)
        if profile["house"] and name not in a.sim.rules["house"]:
            return error("proof_required")
        saved = a.inventories.get(name)
        if saved is not None and saved["owner"] != b["account_id"] and not self._owner_read_decides(b):
            return error("ownership_unavailable")
        number = 0 if saved is None else saved["life_number"] + 1
        if saved is not None:
            profile["bag"] = copy_data(saved["bag"])
            if self._owner_read_decides(b):
                # a saved bag older than the chain (another host filed this token since this arena's base) starts
                # from the chain's bag plus this arena's own moves instead
                newer = a.chain.saved_bag_update(name, saved["bag"], a.sim.rules["items"])
                if newer is not None:
                    profile["bag"] = newer
        elif self._owner_read_decides(b):
            # No life of this token here yet: its gear is what the chain's inventory holds under the token id, whoever
            # owns it now. The read rides with the owner read; until it lands, ask again (as the owner read does).
            chain_bag = a.chain.inventory_bag(name, a.sim.rules["items"])
            if chain_bag is None:
                return error("ownership_unavailable")
            profile["bag"] = chain_bag
        life = name + ":life:" + str(number)
        a.members[name] = {"binding": b, "profile": profile, "life_id": life, "life_number": number,
                           "ordinal": a.ordinal, "queue_order": a.ordinal, "spawn_pending": False, "ever_started": False,
                           "activation_requested": False, "awaiting_life": True, "released": False,
                           "last_receive": -a.sim.rules["intent_interval"], "activation": None}
        a.members[name]["last_sequence"] = "0"
        a.ordinal += 1
        a._life_deadline(a.members[name])
        a._member_changed(name)
        a._op({"op": "join", "name": name, "life_id": life,
               "payload": {"style": profile["style"], "house": profile["house"],
                           "loadout": profile["loadout"], "bag": profile["bag"],
                           "managed": True, "waiting": True, "life_id": life}})
        return {"binding": b, "life_id": life, "prediction_deadline": str(a.members[name]["deadline_ms"])}

    def _owner_read_decides(self, b) -> bool:
        """Whether this binding's owner is read from the identity NFT before its life (mainnet is
        the trenchie's identity; whoever owns the token there controls it and its gear). Then a saved inventory
        follows the token to its new owner, and the chain writer's owner read decides at activation; an arena with
        no such read keeps the inventory to the account that last played it."""
        cfg = getattr(self.arena.chain, "cfg", None)
        nft = ((b.get("context") or {}).get("contract_ids") or {}).get("nft")
        return cfg is not None and nft is not None and nft in (getattr(cfg, "identity_nft", None), getattr(cfg, "nft", None))

    def lock_prediction(self, binding: SlotBinding, life_id: str,
                        signed_pick_or_none: PredictionRequest | None) -> PredictionLock | Error:
        self.arena._prepare_segment()
        a, m = self.arena, self._member(binding)
        if m is None or m["released"]:
            return error("stale_slot")
        if life_id != m["life_id"]:
            return error("prediction_closed")
        pick = copy_data(signed_pick_or_none)
        fingerprint = control_digest(pick)
        existing = a.locks.get(life_id)
        if existing is not None:
            return copy_data(existing["lock"]) if fingerprint == existing["pick_hash"] else error("request_conflict")
        if not m["awaiting_life"] or m["spawn_pending"]:
            return error("prediction_closed")
        if pick is not None:
            if a.sim.state["tick"] >= m["deadline_tick"] or a.server_time_ms() >= m["deadline_ms"]:
                return error("prediction_closed")
            if a.pick_resolver is None:
                return error("bad_message")
            payload = pick["payload"]
            total = a.sim.rules["probability_total"]
            if (type(payload["zero_bps"]) is not int or not 0 <= payload["zero_bps"] <= total
                    or any(type(v) is not int or not 0 <= v <= total for v in payload["spread_bps"].values())
                    or sum(payload["spread_bps"].values()) != total):
                return error("bad_message")
            if payload["moves"] or payload["lock"] or payload["stake"] is not None:
                return error("recovery_pending")
            chosen = copy_data(a.pick_resolver(binding, payload))
            fighter = a.sim.state["fighters"].get(binding["nft_token_id"])
            bag = fighter["bag"] if fighter is not None else m["profile"]["bag"]
            for slot, row in sorted((m.get("bench_kit") or {}).items()):
                # gear the player swapped on at the bench stays on while it is still owned (a KO may have dropped it)
                if slot in chosen and (a.sim.rules["items"][row]["default"] or row in bag):
                    chosen[slot] = row
            a.sim._check_kit(chosen, bag, m["profile"]["house"])
            m["profile"]["loadout"] = chosen
            a._member_changed(binding["nft_token_id"])
            a._op({"op": "loadout", "name": binding["nft_token_id"], "payload": chosen})
        lock = {"life_id": life_id, "lock_ref": sim.digest([life_id, fingerprint]),
                "state": "none" if pick is None else "prediction", "prediction_hash": None if pick is None else fingerprint,
                "ledger_index": str(a.store.index), "locked_before_start": True}
        public = {"life_id": life_id, "nft_token_id": binding["nft_token_id"], "prediction_lock": lock,
                  "pick": None if pick is None else {k: pick[k] for k in (
                      "domain", "context", "grant_id", "session_key_id", "member_id", "nft_token_id",
                      "persona_digest", "slot_id", "generation", "sequence", "life_id", "kind", "payload", "signature") if k in pick}}
        # at_ms: the rarity a level is rewarded at is the base rate published before this moment (arena/predict.py)
        record = {"pick_hash": fingerprint, "lock": lock, "public": public, "at_ms": a.server_time_ms()}
        a._record("lock", record)
        a.locks[life_id] = record
        a._log_player_lock(m, life_id, pick)
        m["activation_requested"] = True
        a._member_changed(binding["nft_token_id"])
        replay_pick = {"loadout": {"menu_row": None, "bag_serials": []} if pick is None else pick["payload"]["loadout"],
                       "moves": [] if pick is None else pick["payload"]["moves"],
                       "lock": False if pick is None else pick["payload"]["lock"], "prediction_lock": lock}
        a._public_event("prediction_lock", binding["nft_token_id"], life_id, replay_pick)
        return copy_data(lock)

    def activate(self, slot_binding: SlotBinding, life_id: str, lock_ref: str) -> FighterBinding | Error:
        self.arena._prepare_segment()
        a, m = self.arena, self._member(slot_binding)
        if m is None or m["released"]:
            return error("stale_slot")
        locked = a.locks.get(life_id)
        if life_id != m["life_id"] or locked is None or locked["lock"]["lock_ref"] != lock_ref:
            return error("prediction_closed")
        if m["activation"] is not None and m["activation"]["life_id"] == life_id:
            return {**copy_data(m["activation"]), "binding": copy_data(slot_binding)}
        m["activation_requested"] = True
        a._member_changed(slot_binding["nft_token_id"])
        f = a.sim.state["fighters"].get(slot_binding["nft_token_id"])
        if f is not None and f["state"] == "bench" and m["ever_started"] and not m["profile"]["house"]:
            # A player's pick locks at the KO; the life still waits out the 45 s respawn timer (plus any held time),
            # and Q5's bench hold keeps it out until the player sends it back in. The room keeps the life queued
            # (room_full) and retries every tick, as it does for a full ring.
            if m.get("bench_hold"):
                return error("room_full")
            if (a.sim.state["tick"] < f["respawn_at"] + m.get("held_ticks", 0)
                    and a._ring_load() >= a.sim.rules["ring_min"]):
                return error("room_full")
        if a._ring_load() >= a.sim.rules["ring_max"]:
            return error("room_full")
        if any(other["queue_order"] < m["queue_order"] and other["activation_requested"]
               and other["awaiting_life"] and not other["spawn_pending"] and not other["released"]
               for other in a.members.values()):
            return error("room_full")
        if not a.life_guard(slot_binding):
            return error("ownership_unavailable")
        name = slot_binding["nft_token_id"]
        announced = a._boundary_start() if a.at_edge() else a.sim.state["tick"] + a.sim.rules["input_delay"]
        start = a._op({"op": "spawn", "name": name, "life_id": life_id, "lock": locked["lock"],
                       "start_tick": str(announced)})
        m["spawn_pending"] = True
        m["activation"] = {"binding": copy_data(slot_binding), "life_id": life_id, "fighter_id": name,
                            "lock_ref": lock_ref, "start_tick": start}
        a._member_changed(name)
        return copy_data(m["activation"])

    def _bench_down(self, m, f):
        return f is not None and f["state"] == "bench" and m["ever_started"]

    def _bench_kit(self, m, f):
        """The kit the next life wears, as the respawn will resolve it (a gear row no longer owned falls back)."""
        r = self.arena.sim.rules
        if f is not None and f["state"] == "alive":
            return dict(f["equipped"])
        bag = f["bag"] if f is not None else m["profile"]["bag"]
        kit = m["profile"]["loadout"]
        return {slot: (row if r["items"][row]["default"] or row in bag else r["default_loadout"][slot]) for slot, row in kit.items()}

    def bench_view(self, name):
        """Board 1's bench card: the hold, the stopped or running timer, the four equipped items and the bag."""
        a = self.arena
        m, f = a.members.get(name), a.sim.state["fighters"].get(name)
        if m is None:
            return {}
        r, tick = a.sim.rules, a.sim.state["tick"]
        names = getattr(a, "item_names", {})
        down = self._bench_down(m, f)
        held = bool(m.get("bench_hold")) and down and not m["spawn_pending"]
        remaining = None
        if down and not m["spawn_pending"]:
            due = f["respawn_at"] + m.get("held_ticks", 0)
            remaining = max(0, due - (m["held_since"] if held and m.get("held_since") is not None else tick))
        ms = lambda ticks: None if ticks is None else ticks * r["milliseconds_per_second"] // r["tick_hz"]
        kit = self._bench_kit(m, f)
        bag = f["bag"] if f is not None else m["profile"]["bag"]
        worn = set(kit.values())
        return {"hold": bool(m.get("bench_hold")), "held": held, "down": down,
                "respawn_in_ms": None if held else ms(remaining), "remaining_ms": ms(remaining),
                "next_life": m["life_number"] + 1, "life_id": m["life_id"],
                "equipped": [{"slot": slot, "item_id": kit[slot], "name": names.get(kit[slot], kit[slot]),
                              "tier": r["items"][kit[slot]]["tier"]} for slot in sorted(kit)],
                "bag": [{"item_id": row, "name": names.get(row, row), "slot": r["items"][row]["slot"],
                         "tier": r["items"][row]["tier"], "serial": bag[row]["serial"]}
                        for row in sorted(bag) if row not in worn]}

    def bench(self, binding, payload):
        """Q5's hold and item 55's swaps, one signed battle frame each. A hold stops the respawn timer (it never
        skips it: the remainder runs after the send-back); a swap changes only the next life's kit, on the bench."""
        a = self.arena
        name, tick = binding["nft_token_id"], a.sim.state["tick"]
        m, f = self._member(binding), a.sim.state["fighters"].get(binding["nft_token_id"])
        names = getattr(a, "item_names", {})

        def ack(status, summary):
            return {"type": "bench_ack", "status": status, "receive_tick": tick, "bench": self.bench_view(name),
                    "summary": summary}
        if m is None or m["released"]:
            return ack("refused", "Bench refused: rejoin with the current grant first.")
        if m["profile"]["house"]:
            return ack("refused", "Bench refused: house Trenchies keep their own kit.")
        down = self._bench_down(m, f)
        if "hold" in payload:
            if payload["hold"]:
                if m.get("bench_hold"):
                    return ack("applied", "Stay on the bench is already on.")
                m["bench_hold"] = True
                if down and not m["spawn_pending"]:
                    m["held_since"] = tick
                    self.arena._fighter_event(name, "held", "On the bench, held. The 45 s timer is stopped.")
                a._member_changed(name)
                return ack("applied", "Held on the bench: the 45 s timer is stopped until you send it back in." if down and not m["spawn_pending"]
                           else "Stay on the bench is on: after its next KO, it waits on the bench until you send it back in.")
            if not m.get("bench_hold"):
                return ack("applied", "Stay on the bench is already off.")
            m["bench_hold"] = False
            was_held = m.get("held_since") is not None
            if was_held:
                m["held_ticks"] = m.get("held_ticks", 0) + tick - m["held_since"]
                m["held_since"] = None
                if m["life_id"] not in a.locks:
                    a._life_deadline(m)  # the pick window reopens: it ran out while the timer was stopped
            a._member_changed(name)
            if not was_held:
                return ack("applied", "Stay on the bench is off.")
            view = self.bench_view(name)
            seconds = (view["remaining_ms"] or 0) // 1000
            self.arena._fighter_event(name, "released", f"Sent back in. Life {view['next_life']} in {seconds} s.")
            return ack("applied", f"Sent back in: life {view['next_life']} starts in {seconds} s.")
        slot, row = payload["equip"]["slot"], payload["equip"]["item_id"]
        if f is None or f["state"] != "bench" or m["spawn_pending"]:
            return ack("refused", "Swap refused: gear changes only on the bench, between lives. Turn on Stay on the bench and swap after the KO.")
        item = a.sim.rules["items"].get(row)
        if item is None or item["slot"] != slot:
            return ack("refused", f"Swap refused: that item does not go in the {slot} slot.")
        bag = f["bag"]
        if not item["default"] and row not in bag:
            return ack("refused", "Swap refused: that item is not in your bag.")
        kit = self._bench_kit(m, f)
        old = kit[slot]
        if old == row:
            return ack("applied", f"{names.get(row, row)} is already on.")
        chosen = {**m["profile"]["loadout"], slot: row}
        try:
            a.sim._check_kit(chosen, bag, False)
        except ValueError as exc:
            return ack("refused", "Swap refused: " + str(exc) + ".")
        a._op({"op": "loadout", "name": name, "payload": {slot: row}})
        m["profile"]["loadout"] = chosen
        m.setdefault("bench_kit", {})[slot] = row
        a._member_changed(name)
        text = f"{names.get(row, row)} goes on; {names.get(old, old)} goes to the bag."
        self.arena._fighter_event(name, "equip", text)
        return ack("applied", text)

    def _public_fighter(self, name, f):
        a = self.arena
        m = a.members[name]
        profile = m["profile"]
        equipped = f["equipped"] if f is not None else profile["loadout"]
        bag = f["bag"] if f is not None else profile["bag"]
        equipment = [{"slot": slot, "item_id": equipped[slot],
                      "serial_id": (equipped[slot] + ":" + str(bag[equipped[slot]]["serial"])) if equipped[slot] in bag else None,
                      "tier": a.sim.rules["items"][equipped[slot]]["tier"]} for slot in sorted(equipped)]
        return {"fighter_id": name, "nft_token_id": m["binding"]["nft_token_id"],
                "persona_digest": m["binding"]["persona_digest"], "public_name": profile["public_name"],
                "model": profile["model"], "x_milli": f["x"] if f else 0, "y_milli": f["y"] if f else 0,
                "health_milli": str((f["hp"] if f else a.sim.rules["base_hp"]) * a.sim.rules["health_scale"]),
                "state": ("disconnected" if f["disconnected_until"] is not None else "ring") if f and f["state"] == "alive" else "bench",
                "house": profile["house"], "equipped": equipment,
                "house_spend_microusd": str(profile.get("house_spend_microusd", 0)) if profile["house"] else None}

    def observe(self, binding: SlotBinding | None) -> PublicSnapshot | Error:
        a = self.arena
        if binding is not None and self._member(binding) is None:
            return error("stale_slot")
        clock = {"type": "clock", "context": a.context, "segment_id": a.segment_id,
                 "tick": str(a.sim.state["tick"]), "tick_hz": a.sim.rules["tick_hz"],
                 "segment_seconds": a.sim.rules["segment_ticks"] // a.sim.rules["tick_hz"],
                 "segment_ticks": str(a.sim.rules["segment_ticks"])}
        fighters = [self._public_fighter(n, a.sim.state["fighters"].get(n)) for n in sorted(a.members)]
        items = [{"serial_id": key, "item_id": a.sim.state["drops"][key]["row"], "holder_token_id": None,
                  "x_milli": a.sim.state["drops"][key]["x"], "y_milli": a.sim.state["drops"][key]["y"]}
                 for key in sim.ordered_ids(a.sim.state["drops"])]
        projectiles, telegraphs, actions = [], [], []
        tick = a.sim.state["tick"]
        r = a.sim.rules
        for key in sim.ordered_ids(a.sim.state["objects"]):
            obj = a.sim.state["objects"][key]
            remaining = max(0, obj["range"] - obj.get("travelled", 0))
            speed = max(1, sim.isqrt(obj.get("vx", 0) ** 2 + obj.get("vy", 0) ** 2))
            expires = tick + (remaining + speed - 1) // speed if obj["kind"] == "shot" else obj.get("until", obj["resolve_at"])
            projectiles.append({"projectile_id": key, "fighter_id": obj["owner"], "item_id": obj["item_id"],
                                "x_milli": obj["x"], "y_milli": obj["y"], "vx_milli_per_tick": obj.get("vx", 0),
                                "vy_milli_per_tick": obj.get("vy", 0), "radius_milli": str(obj.get("radius", r["body_radius"])),
                                "expires_tick": str(expires)})
            if obj["kind"] in ("beam", "lob"):
                dx, dy = sim.vector(obj["angle"], r["tile"], r)
                telegraphs.append({"telegraph_id": key, "fighter_id": obj["owner"], "item_id": obj["item_id"],
                                   "shape": "circle" if obj["kind"] == "lob" else "line",
                                   "x_milli": obj["target_x"] if obj["kind"] == "lob" else obj["x"],
                                   "y_milli": obj["target_y"] if obj["kind"] == "lob" else obj["y"],
                                   "direction_x_milli": dx, "direction_y_milli": dy,
                                   "radius_milli": str(obj.get("radius", obj["range"])), "width_milli": str(obj.get("width", 0)),
                                   "arc_millidegrees": "0", "start_tick": str(obj["start_tick"]), "end_tick": str(obj["resolve_at"])})
        for name in a.sim._live():
            f = a.sim.state["fighters"][name]
            cast = f["cast"]
            if cast is None:
                continue
            s = cast.get("parameters", r["signatures"][cast["kind"]])
            dx, dy = sim.normalise(cast["x"] - f["x"], cast["y"] - f["y"], r["tile"])
            telegraphs.append({"telegraph_id": "cast:" + name, "fighter_id": name, "item_id": cast["item_id"],
                               "shape": "cone" if cast["kind"] == "beam_sweep" else "circle",
                               "x_milli": cast["x"] if cast["kind"] == "blink_strike" else f["x"],
                               "y_milli": cast["y"] if cast["kind"] == "blink_strike" else f["y"],
                               "direction_x_milli": dx, "direction_y_milli": dy,
                               "radius_milli": str(s["range"] * cast.get("sig_range_pct", f["sig_range_pct"]) // r["percent"]),
                               "width_milli": str(s.get("width", 0)),
                               "arc_millidegrees": str(s.get("half_arc", 0) * 2 * r["tile"]),
                               "start_tick": str(cast["start_tick"]), "end_tick": str(cast["resolve_at"])})
        event_types = {"attack": "attack", "signature": "use", "grab": "pickup", "hit": "damage",
                       "ko": "ko", "respawn": "respawn", "leave": "leave"}
        for index, event in enumerate(a.sim.state["events"]):
            if event["kind"] not in event_types:
                continue
            name = event.get("fighter", event.get("source"))
            f = a.sim.state["fighters"].get(name)
            if f is None:
                continue
            actions.append({"index": str(index), "tick": str(tick), "fighter_id": name,
                            "target_fighter_id": event.get("target", event.get("source")) if event.get("source") != name else event.get("target"),
                            "kind": event_types[event["kind"]], "item_serial_id": None,
                            "x_milli": f["x"], "y_milli": f["y"],
                            "value_milli": event["damage"] * r["health_scale"] if "damage" in event else None, "text": None})
        snapshot = {"type": "snapshot", "context": a.context, "clock": clock, "fighters": fighters, "items": items,
                    "projection_version": r["snapshot_version"], "projectiles": projectiles, "telegraphs": telegraphs, "actions": actions}
        snapshot["snapshot_hash"] = sim.digest(snapshot)
        return copy_data(snapshot)

    def _receipt(self, binding, message, row):
        a = self.arena
        body = {"domain": "room.receipt.v1", "context": a.context, "grant_id": binding["grant_id"],
                "session_key_id": binding["session_key_id"], "owner": None, "request_id": None,
                "sequence": message["sequence"], "message_domain": "room.control.v1",
                "request_digest": control_digest(message), "state": "accepted", "applied_tick": str(row.tick),
                "boundary": None, "prediction_lock": None, "code": None}
        return a.receipt_signer(copy_data(body))

    def apply(self, binding: SlotBinding, sequenced_input: IntentRequest) -> Receipt | Error:
        self.arena._prepare_segment()
        if sequenced_input.get('kind') == 'behaviour':
            try:
                from .battle_engine import apply_behaviour
            except ImportError:
                from battle_engine import apply_behaviour
            return apply_behaviour(self, binding, sequenced_input)
        a, m = self.arena, self._member(binding)
        if m is None or m["released"]:
            return error("stale_slot")
        message = copy_data(sequenced_input)
        name = binding["nft_token_id"]
        f = a.sim.state["fighters"].get(name)
        if message.get("life_id") != m["life_id"] or f is None or f["state"] != "alive":
            return error("prediction_closed")
        if message.get("kind") != "intent" or message["payload"].get("fighter_id") != name:
            return error("bad_message")
        key = sim.digest([a.context, binding["grant_id"], binding["session_key_id"], message["sequence"]])
        prior = a.receipts.get(key)
        fingerprint = control_digest(message)
        if prior is not None:
            return copy_data(prior["receipt"]) if prior["request_hash"] == fingerprint else error("request_conflict")
        if a.at_edge():
            return edge_error(a.sim.rules)
        if a.sim.state["tick"] - m["last_receive"] < a.sim.rules["intent_interval"]:
            return error("rate_limited")
        payload = {k: message["payload"][k] for k in ("focus", "avoid", "loot", "sig", "leave")}
        row = a._enqueue("intent", name, payload)
        m["last_receive"] = a.sim.state["tick"]
        m["last_sequence"] = message["sequence"]
        a._member_changed(name)
        public = {"fighter_id": name, **payload, "say": None}
        a._public_event("intent", name, m["life_id"], public, row.tick)
        receipt = self._receipt(binding, message, row)
        stored = {"key": key, "request_hash": fingerprint, "receipt": receipt}
        a._record("receipt", stored)
        a.receipts[key] = stored
        return copy_data(receipt)

    def release(self, binding: SlotBinding) -> ReleaseAck | Error:
        self.arena._prepare_segment()
        a, m = self.arena, self._member(binding)
        if m is None:
            return error("stale_slot")
        if not m["released"]:
            name = binding["nft_token_id"]
            m["spawn_pending"] = False
            m["activation_requested"] = False
            m["released"] = True                  # the room sees the release at once, even on the last two ticks
            a._op({"op": "leave", "name": name, "life_id": m["life_id"]})
            a._member_changed(name)
        return {"binding": copy_data(binding), "last_sequence": m.get("last_sequence", "0"), "revoked": True,
                "boundary": {"kind": "released", "life_id": m["life_id"], "segment_id": a.segment_id, "not_before_ms": None}}

    def sale_control(self, owner_binding: OwnerBinding, action: SaleAction, request_id: str) -> SaleAcknowledgement | Error:
        if self.arena.sale_adapter is None:
            return error("recovery_pending")
        return self.arena.sale_adapter(owner_binding, action, request_id)

    def seal(self, segment_id: str) -> SealedRecord | Error:
        try:
            return copy_data(self.arena.store.segment(segment_id)["sealed"])
        except (FileNotFoundError, ValueError):
            return error("result_pending")


if __name__ == "__main__":
    raise SystemExit("room service and game adapters required; admission closed")
