"""One durable slot writer for trusted local and service admission callers.

Callers authenticate the member and verify persona eligibility before reserve,
join or resume. Bindings returned here are internal authority handles, never a
substitute for signed service grants. No method executes member code. The state
file is authoritative; numbered JSON files are replaceable reader projections.
The directory must be private to the service, never writable by a member.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time


class SlotError(ValueError):
    """A bounded error without member input or authority handles."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _text(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 for c in value):
        raise SlotError("bad_message")
    return value


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SlotError("bad_message")
    return value


def _atomic(path, value):
    fd, name = tempfile.mkstemp(prefix=".slot-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class SlotStore:
    """Serialised admission, leases and FIFO waiting with server millisecond time.

    The lease defaults are 60s for reservations, 30s for live grants and 30s for
    disconnect grace. Heartbeats should arrive every 10s. A resume rotates both
    generation and grant; application checks must call authorize at dispatch.
    Recovery and signed-context checks belong to the surrounding service.
    Capacity is durable authority shared by every writer. An incompatible
    caller or legacy state without a capacity is refused before any mutation;
    a trusted operator must explicitly reconcile such state while stopped.
    """

    def __init__(self, directory, room_id, capacity, *, clock=None,
                 reservation_ms=60_000, lease_ms=30_000, grace_ms=30_000,
                 offer_ms=60_000, house_floor=2):
        self.directory = Path(directory)
        self.room_id = _text(room_id)
        if type(capacity) is not int or not 1 <= capacity <= 1024:
            raise SlotError("bad_message")
        self.capacity = capacity
        for value in (reservation_ms, lease_ms, grace_ms, offer_ms):
            if type(value) is not int or not 1 <= value <= 86_400_000:
                raise SlotError("bad_message")
        if type(house_floor) is not int or not 0 <= house_floor <= 1024:
            raise SlotError("bad_message")
        self.reservation_ms, self.lease_ms = reservation_ms, lease_ms
        self.grace_ms, self.offer_ms, self.house_floor = grace_ms, offer_ms, house_floor
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "slots").mkdir(exist_ok=True)

    @contextmanager
    def _transaction(self):
        # Never unlink the lock: all processes must lock the same inode.
        with (self.directory / ".slots.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.directory / ".slots-state.json"
            if path.exists():
                state = json.loads(path.read_text(encoding="utf-8"))
                if (state["room_id"] != self.room_id
                        or type(state.get("capacity")) is not int
                        or state["capacity"] != self.capacity):
                    raise SlotError("context_mismatch")
            else:
                state = dict(room_id=self.room_id, capacity=self.capacity, slots={}, generations={}, queue=[],
                             next_order=0, offers={})
            self._now = self.clock()
            if type(self._now) is not int or not 0 <= self._now < 2 ** 64:
                raise SlotError("bad_message")
            self._expire(state)
            self._drain(state)
            baseline = deepcopy(state)
            try:
                yield state
            except BaseException:
                state = baseline
                raise
            finally:
                # Expiry is durable even when the requested operation is stale.
                _atomic(path, state)
                self._publish(state)

    def _public(self, slot):
        return deepcopy(slot["record"])

    def _publish(self, state):
        for slot_id, slot in state["slots"].items():
            path = self.directory / "slots" / (slot_id + ".json")
            if slot["record"]["state"] == "released":
                path.unlink(missing_ok=True)
            else:
                # Only a trusted local caller can supply launcher fields.
                _atomic(path, {**slot.get("local_fields", {}), **slot["record"]})

    def _active(self, state):
        return [s for s in state["slots"].values() if s["record"]["state"] != "released"]

    def _expire(self, state):
        for slot in self._active(state):
            deadline = slot["record"]["lease_until"]
            # Local supervisors explicitly release; service slots always lease.
            timed = not slot.get("supervised") or slot["record"]["state"] == "disconnected"
            if timed and int(deadline) <= self._now:
                if slot["house"] and slot["in_life"]:
                    # Expiry removes control immediately, but the engine must
                    # finish the house life before its place can be reused.
                    slot["record"]["state"] = "disconnected"
                else:
                    slot["record"]["state"] = "released"

    def _generation(self, state, slot_id):
        generation = int(state["generations"].get(slot_id, "0")) + 1
        if generation >= 2 ** 64:
            raise SlotError("stale_slot")
        state["generations"][slot_id] = str(generation)
        return str(generation)

    def _free(self, state):
        occupied = {s["record"]["slot_id"] for s in self._active(state)}
        # A pre-existing local projection is occupied until its supervisor
        # migrates or releases it. Never overwrite an unknown live occupant.
        occupied.update(p.stem for p in (self.directory / "slots").glob("*.json")
                        if p.stem.isdecimal() and p.stem not in state["slots"])
        return [str(i) for i in range(1, self.capacity + 1) if str(i) not in occupied]

    def _allocate(self, state, waiter, slot_id):
        record = dict(slot_id=slot_id, generation=self._generation(state, slot_id),
                      member_id=waiter["member_id"], persona_digest=waiter["persona_digest"],
                      harness="", model="", source="", effort="", grant=secrets.token_urlsafe(32),
                      lease_until=str(self._now + self.reservation_ms), state="reserved")
        state["slots"][slot_id] = dict(record=record, capability=waiter["capability"],
                                       house=False, in_life=False, supervised=False,
                                       request=deepcopy(waiter.get("request")))
        state["offers"].pop(slot_id, None)
        return self._public(state["slots"][slot_id])

    def _drain(self, state):
        for slot_id in self._free(state):
            for index, waiter in enumerate(state["queue"]):
                if waiter["eligible"] and waiter.get("slot_id") in (None, slot_id):
                    state["queue"].pop(index)
                    self._allocate(state, waiter, slot_id)
                    break

    def _slot_id(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
            raise SlotError("bad_message")
        if int(value) > self.capacity:
            raise SlotError("room_full")
        return value

    def _current(self, state, binding, allowed):
        if not isinstance(binding, dict):
            raise SlotError("stale_slot")
        slot_id = self._slot_id(binding.get("slot_id"))
        slot = state["slots"].get(slot_id)
        if slot is None:
            raise SlotError("stale_slot")
        record = slot["record"]
        if record["state"] not in allowed or any(
                binding.get(k) != record[k] for k in
                ("generation", "member_id", "persona_digest", "grant")):
            raise SlotError("stale_slot")
        timed = not slot.get("supervised") or record["state"] == "disconnected"
        if timed and int(record["lease_until"]) <= self._now:
            raise SlotError("stale_slot")
        return slot

    def manifest(self):
        """Public offers contain no grant or private launcher metadata."""
        with self._transaction() as state:
            offers = []
            for slot_id in self._free(state):
                offer = state["offers"].get(slot_id)
                if offer is None or int(offer["expires_at"]) <= self._now:
                    offer = dict(slot_id=slot_id, capability="fighter",
                                 expires_at=str(self._now + self.offer_ms))
                    state["offers"][slot_id] = offer
                offers.append(deepcopy(offer))
            return dict(room_id=self.room_id, capacity=self.capacity,
                        occupied=self.capacity - len(self._free(state)), offers=offers)

    def spectate(self):
        return {**self.manifest(), "read_only": True}

    def reserve(self, member_id, persona_digest, *, capability="fighter", slot_id=None, offer=None):
        """Retry an active reservation with its original context, even after
        its public offer was consumed. Omitted context also permits a member
        to retrieve its current binding; supplied context must match exactly.
        """
        _text(member_id)
        _digest(persona_digest)
        if capability != "fighter":
            raise SlotError("bad_message")
        if slot_id is not None:
            self._slot_id(slot_id)
        with self._transaction() as state:
            request = dict(capability=capability, slot_id=slot_id, offer=deepcopy(offer))
            for slot in self._active(state):
                record = slot["record"]
                if record["member_id"] == member_id:
                    if record["persona_digest"] != persona_digest:
                        raise SlotError("request_conflict")
                    self._retry_context(slot, request)
                    return self._public(slot)
                if record["persona_digest"] == persona_digest:
                    raise SlotError("room_full")
            for waiter in state["queue"]:
                if waiter["persona_digest"] == persona_digest and waiter["member_id"] != member_id:
                    raise SlotError("room_full")
                if waiter["member_id"] == member_id:
                    if waiter["persona_digest"] != persona_digest:
                        raise SlotError("request_conflict")
                    self._retry_context(waiter, request)
                    return self._waiting(state, member_id)
            if offer is not None:
                if not isinstance(offer, dict):
                    raise SlotError("bad_message")
                offered_id = self._slot_id(offer.get("slot_id"))
                if (state["offers"].get(offered_id) != offer
                        or int(offer["expires_at"]) <= self._now
                        or offer["capability"] != capability
                        or slot_id not in (None, offered_id)):
                    raise SlotError("stale_slot")
                slot_id = offered_id
            state["next_order"] += 1
            state["queue"].append(dict(member_id=member_id, persona_digest=persona_digest,
                                       capability=capability, slot_id=slot_id, eligible=True,
                                       order=state["next_order"], request=request))
            self._drain(state)
            for slot in self._active(state):
                if slot["record"]["member_id"] == member_id:
                    return self._public(slot)
            return self._waiting(state, member_id)

    def _retry_context(self, existing, request):
        original = existing.get("request") or {}
        if (existing["capability"] != request["capability"]
                or any(request[key] is not None and request[key] != original.get(key)
                       for key in ("slot_id", "offer"))):
            raise SlotError("request_conflict")

    def _waiting(self, state, member_id):
        position = next(i + 1 for i, w in enumerate(state["queue"]) if w["member_id"] == member_id)
        return dict(state="spectating", member_id=member_id, queue_position=position, read_only=True)

    def _join(self, slot, compute, *, house=False, local_fields=None):
        if not isinstance(compute, dict) or set(compute) != {"harness", "model", "source", "effort"}:
            raise SlotError("bad_message")
        for key, value in compute.items():
            if value != "" or key not in {"model", "effort"}:
                _text(value)
        if type(house) is not bool:
            raise SlotError("bad_message")
        if slot["record"]["state"] == "joined":
            if any(slot["record"][k] != v for k, v in compute.items()) or slot["house"] != house:
                raise SlotError("request_conflict")
            return self._public(slot)
        slot["record"].update(compute, state="joined", lease_until=str(self._now + self.lease_ms))
        slot["house"] = house
        if local_fields is not None:
            slot["local_fields"] = deepcopy(local_fields)
            slot["supervised"] = True
        return self._public(slot)

    def join(self, binding, compute, *, house=False):
        """Bind verified compute labels; never create a launcher or run code."""
        with self._transaction() as state:
            return self._join(self._current(state, binding, {"reserved", "joined"}), compute, house=house)

    def authorize(self, binding):
        with self._transaction() as state:
            return self._public(self._current(state, binding, {"joined"}))

    def renew(self, binding):
        with self._transaction() as state:
            slot = self._current(state, binding, {"joined"})
            slot["record"]["lease_until"] = str(self._now + self.lease_ms)
            return self._public(slot)

    def disconnect(self, binding):
        with self._transaction() as state:
            slot = self._current(state, binding, {"joined", "disconnected"})
            if slot["record"]["state"] == "joined":
                slot["record"].update(state="disconnected", lease_until=str(self._now + self.grace_ms))
            return self._public(slot)

    def resume(self, binding):
        """Call only after verifying fresh owner proof or a resume credential."""
        with self._transaction() as state:
            slot = self._current(state, binding, {"joined", "disconnected"})
            slot["record"].update(generation=self._generation(state, slot["record"]["slot_id"]),
                                  grant=secrets.token_urlsafe(32), state="joined",
                                  lease_until=str(self._now + self.lease_ms))
            return self._public(slot)

    def release(self, binding):
        with self._transaction() as state:
            slot = self._current(state, binding, {"reserved", "joined", "disconnected"})
            self._release(slot)
            self._drain(state)

    def _release(self, slot):
        if slot["house"] and slot["in_life"]:
            slot["record"].update(state="disconnected", lease_until=str(self._now))
        else:
            slot["record"]["state"] = "released"

    def expire(self):
        with self._transaction():
            pass

    def set_eligible(self, member_id, eligible):
        """Trusted admission policy may skip an ineligible waiter without reordering."""
        _text(member_id)
        if type(eligible) is not bool:
            raise SlotError("bad_message")
        with self._transaction() as state:
            for waiter in state["queue"]:
                if waiter["member_id"] == member_id:
                    waiter["eligible"] = eligible
            self._drain(state)

    def start_life(self, binding):
        with self._transaction() as state:
            self._current(state, binding, {"joined"})["in_life"] = True

    def life_boundary(self, binding):
        """The engine calls this after a life ends, before reserving the next."""
        with self._transaction() as state:
            slot_id = self._slot_id(binding.get("slot_id"))
            slot = state["slots"].get(slot_id)
            expired_house = (slot is not None and slot["house"] and slot["in_life"]
                             and slot["record"]["state"] == "disconnected"
                             and int(slot["record"]["lease_until"]) <= self._now)
            if expired_house:
                if any(binding.get(k) != slot["record"][k] for k in
                       ("generation", "member_id", "persona_digest", "grant")):
                    raise SlotError("stale_slot")
                slot["in_life"] = False
                slot["record"]["state"] = "released"
                self._drain(state)
                return
            slot = self._current(state, binding, {"joined"})
            slot["in_life"] = False
            houses = sum(s["house"] for s in self._active(state))
            if slot["house"] and houses > self.house_floor and any(
                    w["eligible"] and w.get("slot_id") in (None, slot_id) for w in state["queue"]):
                slot["record"]["state"] = "released"
                self._drain(state)

    def local_fill(self, slot_id, member_id, persona_digest, compute, fields, *, preserve=False, house=False, replace=True):
        """Trusted supervisor adapter: same records, local-only launcher fields.

        Explicit replacement rotates authority; a model change may preserve the
        current occupant. A remote occupant is never replaced through this API.
        """
        self._slot_id(slot_id)
        _text(member_id)
        _digest(persona_digest)
        if not isinstance(fields, dict) or set(fields) & {
                "slot_id", "generation", "member_id", "persona_digest", "grant", "lease_until", "state"}:
            raise SlotError("bad_message")
        with self._transaction() as state:
            existing = state["slots"].get(slot_id)
            if existing and existing["record"]["state"] != "released":
                if not replace or not existing.get("supervised"):
                    raise SlotError("room_full")
                if preserve and existing["record"]["member_id"] == member_id:
                    # Compute changes keep occupant authority but replace local launch metadata.
                    existing["record"]["state"] = "reserved"
                    return self._join(existing, compute, house=house, local_fields=fields)
                existing["record"]["state"] = "released"
            if any(w["eligible"] and w.get("slot_id") in (None, slot_id) for w in state["queue"]):
                raise SlotError("room_full")
            if any(s["record"]["member_id"] == member_id or s["record"]["persona_digest"] == persona_digest
                   for s in self._active(state)):
                raise SlotError("room_full")
            waiter = dict(member_id=member_id, persona_digest=persona_digest, capability="fighter")
            record = self._allocate(state, waiter, slot_id)
            return self._join(state["slots"][record["slot_id"]], compute, house=house, local_fields=fields)

    def local_release(self, slot_id):
        """Trusted supervisor only; network release requires a current binding."""
        self._slot_id(slot_id)
        with self._transaction() as state:
            slot = state["slots"].get(slot_id)
            if slot and slot["record"]["state"] != "released":
                if not slot.get("supervised"):
                    raise SlotError("stale_slot")
                self._release(slot)
            elif slot is None:
                # Migration of a legacy local slot has no portable authority.
                (self.directory / "slots" / (slot_id + ".json")).unlink(missing_ok=True)
            self._drain(state)
