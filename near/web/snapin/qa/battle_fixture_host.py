#!/usr/bin/env python3
"""battle_fixture_host.py: a FIXTURE of the signed battle envelope v1 (the battle protocol contract), on the real DEV host.

  python3 -B near/web/snapin/qa/battle_fixture_host.py [--port 8765]

Everything is near/arena/snap_local.py's DEV arena (identity, join, terms, controls, the sim), except frames with
domain "arena.battle.v1" on /room/control/frame. This file answers those itself, in the contract's shape, so the browser
client (snapin/room.js SnapRoom.behaviour / speech) can be built and checked before the host side lands:
  * the request's session signature is checked against the joiner's registered key (refused: the room's Error);
  * the reply is the flat binding + domain "arena.battle.receipt.v1", type "battle_receipt", kind, sequence, life_id,
    request_digest (the whole request minus its signature), ack, key_id "room_key_a", signed with the DEV room key;
  * the inner ack is a stand-in: behaviour -> {state applied|refused, summary, tick, fixes}; speech -> {type speech_ack,
    status posted, receive_tick, speech, summary}. Its words are the fixture's, not the engine's.
POST /fixture/tamper {"mode": ...} (straight to this port) makes the next replies wrong on purpose, one checked field at a
time (digest, binding, signature, kind, sequence, life_id, type, domain, key_id, no_ack, no_summary, summary_number), or an
unsigned error whose code is markup (error_html), to prove the client refuses each. Test tooling: never run it as the arena.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

NEAR = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(NEAR.parent), str(NEAR / "arena")]
import snap_local  # noqa: E402
from room.policy import canonical_bytes, digest  # noqa: E402

BINDING = ("context", "grant_id", "session_key_id", "member_id", "nft_token_id", "persona_digest", "slot_id", "generation")


class FixtureRoom(snap_local.DevRoom):
    tamper = ""

    def route(self, method, target, body, ip, admin=""):
        path = urlsplit(target).path
        if path == "/fixture/tamper" and method == "POST":
            self.tamper = str(json.loads(body or b"{}").get("mode", ""))
            return 200, {"tamper": self.tamper}
        if method == "POST" and path == "/room/control/frame":
            try:
                req = json.loads(body)
            except ValueError:
                req = None
            if isinstance(req, dict) and req.get("domain") == "arena.battle.v1":
                return 200, self.battle(req)
        return super().route(method, target, body, ip, admin)

    def battle(self, req: dict) -> dict:
        rec = self.identities.get(req.get("nft_token_id"))
        if rec is None or not snap_local.verify_ed25519(rec["session_public_key"]["public_key"], canonical_bytes(req, exclude=("signature",)), str(req.get("signature", ""))):
            return {"type": "error", "code": "proof_required", "request_id": None, "retry_after_ms": None}
        tick = str(self.round.arena.sim.state["tick"])
        payload = req.get("payload") or {}
        if req.get("kind") == "speech":
            ack = {"type": "speech_ack", "status": "posted", "receive_tick": tick,
                   "speech": {"text": str(payload.get("text", ""))[:280], "emoji": payload.get("emoji")},
                   "summary": "Posted to the feed (fixture)."}
        elif isinstance(payload, dict) and payload.get("target") == "goblin":
            ack = {"type": "behaviour_ack", "state": "refused", "summary": "No fighter called goblin is in the ring (fixture).", "tick": tick,
                   "fixes": ["Name a fighter in the ring, or say nearest."]}
        else:
            ack = {"type": "behaviour_ack", "state": "applied", "summary": "New drive recorded: " + " · ".join(f"{k} {v}" for k, v in sorted((payload.get("drives") or {}).items())) + " (fixture)",
                   "tick": tick, "fixes": []}
        receipt = {k: copy.deepcopy(req[k]) for k in BINDING}
        receipt.update(domain="arena.battle.receipt.v1", type="battle_receipt", kind=req.get("kind"), sequence=req.get("sequence"),
                       life_id=req.get("life_id"), request_digest=digest(req, exclude=("signature",)), ack=ack, key_id="room_key_a")
        # each field the client checks, made wrong on purpose (then signed, so only the field itself is wrong)
        t = self.tamper
        if t == "error_html":
            return {"type": "error", "code": "<img src=x onerror=alert(1)>", "request_id": None, "retry_after_ms": None}
        wrong = {"digest": ("request_digest", "0" * 64), "binding": ("grant_id", "grant:someone-else"), "kind": ("kind", "speech" if receipt["kind"] == "behaviour" else "behaviour"),
                 "sequence": ("sequence", str(int(receipt["sequence"]) + 7)), "life_id": ("life_id", "someone:life:9"), "type": ("type", "control_receipt"),
                 "domain": ("domain", "arena.battle.v1"), "key_id": ("key_id", "room_key_b"), "summary_number": None}
        if t in wrong and wrong[t]:
            receipt[wrong[t][0]] = wrong[t][1]
        if t == "no_ack":
            del receipt["ack"]
        if t == "no_summary":
            receipt["ack"].pop("summary", None)
        if t == "summary_number":
            receipt["ack"]["summary"] = 42
        receipt["signature"] = self.room_sign(canonical_bytes(receipt, exclude=("signature",)))
        if self.tamper == "signature":
            receipt["signature"] = ("A" if receipt["signature"][0] != "A" else "B") + receipt["signature"][1:]
        return receipt


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    data_dir = tempfile.mkdtemp(prefix="battle-fixture-")
    dev = FixtureRoom(args.port, data_dir)
    print(f"battle_fixture_host: FIXTURE of the battle envelope on the DEV arena http://127.0.0.1:{args.port}; data {data_dir}. "
          f"POST /dev/shutdown with header X-Dev-Admin: {dev.admin}", flush=True)
    try:
        asyncio.run(snap_local.serve(dev))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
