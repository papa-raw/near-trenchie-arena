"""The two ways the writer sends: for real (`RpcSender`, `--chain testnet`), or not at all (`DryRun`, default).

Both return the same outcome dict, so the writer's decisions never depend on which one runs:
  landed: True (a final result came back), False (the node refused it before inclusion), None (unknown)
  ok, value, failure, receipt_failures, logs, events, tgas, tx
A dry-run prints every call it would send (signer, receiver, method, gas, deposit and the exact argument
bytes) and simulates the result with the contract model; its tx ids read `DRY-RUN-<n>`, never a hash.
"""

import hashlib
import json
import sys

from . import near_tx, rpc as rpclib
from .model import Panic


class RpcSender:
    label = "testnet"

    def __init__(self, rpc: rpclib.Rpc, keys: dict):
        self.rpc = rpc
        self.keys = keys          # role -> near_tx.Key

    def account(self, role):
        return self.keys[role].account_id

    def call(self, role, receiver, method, args, tgas, deposit=0):
        key = self.keys[role]
        try:
            ak = self.rpc.access_key(key.account_id, key.public_key)
        except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
            return {"landed": False, "tx": None, "failure": f"access key lookup failed: {exc}"}
        if "nonce" not in ak:
            return {"landed": False, "tx": None, "failure": f"access key lookup failed: {json.dumps(ak)[:300]}"}
        action = near_tx.Action(method, args, tgas, deposit)
        tx_hash, signed = near_tx.sign_tx(key, ak["nonce"] + 1, receiver, near_tx.b58decode(ak["block_hash"]), [action])
        try:
            res = self.rpc.send(near_tx.b64(signed))
        except rpclib.RpcError as exc:
            if exc.name in ("TIMEOUT_ERROR", "REQUEST_ROUTED"):
                return {"landed": None, "tx": tx_hash, "failure": str(exc)}
            return {"landed": False, "tx": tx_hash, "failure": str(exc)}
        except rpclib.RpcUnreachable as exc:
            return {"landed": None, "tx": tx_hash, "failure": str(exc)}
        out = rpclib.outcome(res)
        out["tx"] = tx_hash
        return out

    def tx_status(self, tx_hash, role):
        """The final outcome of a sent tx, or None when no node knows it (it never landed)."""
        try:
            res = self.rpc.tx(tx_hash, self.keys[role].account_id)
        except rpclib.RpcError as exc:
            if exc.name == "UNKNOWN_TRANSACTION":
                return None
            raise
        out = rpclib.outcome(res)
        out["tx"] = tx_hash
        return out

    def view(self, receiver, method, args=None):
        return self.rpc.view(receiver, method, args)


class DryRun:
    """Sends nothing. Prints each call exactly, then runs it on the model so the arena can keep going."""

    label = "dry-run"

    def __init__(self, model, accounts: dict, out=None, full_args_limit=2048, calls_path=None):
        self.model = model
        self.accounts = accounts  # role -> account id
        self.out = out or sys.stdout
        self.full_args_limit = full_args_limit
        self.calls_path = calls_path  # every call with its full args, one JSON line each
        self.n = 0
        self.sent = []

    def account(self, role):
        return self.accounts[role]

    def call(self, role, receiver, method, args, tgas, deposit=0):
        near_tx.Action(method, args, tgas, deposit)       # the same checks the real sender makes
        raw = near_tx.args_bytes(args)
        self.n += 1
        tx = f"DRY-RUN-{self.n}"
        line = {"dry_run": tx, "signer": self.accounts[role], "receiver": receiver, "method": method,
                "tgas": tgas, "deposit_yocto": str(deposit), "args_bytes": len(raw),
                "args_sha256": hashlib.sha256(raw).hexdigest()}
        if len(raw) <= self.full_args_limit:
            line["args"] = args
        elif self.calls_path:
            line["full_args_in"] = str(self.calls_path)
        print("DRY-RUN would send (not onchain): " + json.dumps(line, separators=(",", ":")), file=self.out, flush=True)
        if self.calls_path:
            with open(self.calls_path, "a") as f:
                f.write(json.dumps(dict(line, args=args), separators=(",", ":")) + "\n")
        self.sent.append(dict(line, args=args))
        try:
            value, logs, failures = self.model.call(self.accounts[role], receiver, method, args)
        except Panic as exc:
            return {"landed": True, "ok": False, "tx": tx, "value": None, "failure": str(exc), "receipt_failures": [],
                    "logs": [], "events": [], "tgas": 0}
        events = [json.loads(line[len("EVENT_JSON:"):]) for line in logs if line.startswith("EVENT_JSON:")]
        return {"landed": True, "ok": True, "tx": tx, "value": value, "failure": None, "receipt_failures": failures,
                "logs": logs, "events": events, "tgas": 0}

    def tx_status(self, tx_hash, role):
        return None

    def view(self, receiver, method, args=None):
        return self.model.view(receiver, method, args or {})
