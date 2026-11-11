"""A fake NEAR JSON-RPC endpoint for tests: the real signing, sending and retry code runs against it.

`FakeRpc.post` has the shape of `requests.post`. It decodes each signed transaction (near_tx), checks the
signature, the access key and the nonce, runs the call on the contract model, and answers in the node's
own result shapes (`send_tx`, `EXPERIMENTAL_tx_status`, `query`). Fault switches:
  * `drop_responses`: the tx executes but the caller sees a timeout (the outcome is unknown to it);
  * `refuse_next`: the node refuses the tx before inclusion (InvalidTxError);
  * `model.fail_next_hops`: the `apply_rows` hop fails as it did on testnet (out of gas).
Test-only: it never pretends to be testnet in any output.
"""

import base64
import hashlib
import json as jsonlib

import requests

from . import near_tx
from .model import Panic


class _Response:
    def __init__(self, body, status=200):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeRpc:
    def __init__(self, model):
        self.model = model
        self.keys = {}            # (account, public key) -> nonce
        self.txs = {}             # hash -> final result
        self.drop_responses = 0
        self.refuse_next = 0
        self.sent = []

    def add_key(self, key: near_tx.Key):
        self.keys[(key.account_id, key.public_key)] = 7

    def post(self, url, json=None, timeout=None):
        method, params = json["method"], json["params"]
        try:
            result = getattr(self, "_" + method)(params)
        except _RpcFail as exc:
            return _Response({"jsonrpc": "2.0", "id": json["id"], "error": exc.data})
        if result is _TIMEOUT:
            raise requests.exceptions.ReadTimeout("fake: response lost after execution")
        return _Response({"jsonrpc": "2.0", "id": json["id"], "result": result})

    # ------------------------------------------------------------------ query
    def _query(self, p):
        if p["request_type"] == "view_access_key":
            nonce = self.keys.get((p["account_id"], p["public_key"]))
            if nonce is None:
                raise _RpcFail({"name": "HANDLER_ERROR", "cause": {"name": "UNKNOWN_ACCESS_KEY"}})
            return {"nonce": nonce, "permission": "FullAccess", "block_hash": near_tx.b58encode(b"\x11" * 32),
                    "block_height": self.model.height}
        if p["request_type"] == "call_function":
            args = jsonlib.loads(base64.b64decode(p["args_base64"]) or b"{}")
            try:
                value = self.model.view(p["account_id"], p["method_name"], args)
            except Panic as exc:
                return {"error": str(exc), "logs": [], "block_height": self.model.height}
            return {"result": list(jsonlib.dumps(value).encode()), "logs": [],
                    "block_height": self.model.height}
        raise _RpcFail({"name": "REQUEST_VALIDATION_ERROR"})

    # ------------------------------------------------------------------ txs
    def _send_tx(self, p):
        signed = base64.b64decode(p["signed_tx_base64"])
        tx = near_tx.decode_signed_tx(signed)      # raises on a bad signature
        if self.refuse_next:
            self.refuse_next -= 1
            raise _RpcFail({"name": "HANDLER_ERROR", "cause": {"name": "INVALID_TRANSACTION"},
                            "data": {"TxExecutionError": {"InvalidTxError": "fake refusal"}}})
        k = (tx["signer_id"], tx["public_key"])
        if k not in self.keys:
            raise _RpcFail({"name": "HANDLER_ERROR", "cause": {"name": "INVALID_TRANSACTION"},
                            "data": {"TxExecutionError": {"InvalidTxError": {"InvalidAccessKeyError": "AccessKeyNotFound"}}}})
        if tx["nonce"] <= self.keys[k]:
            raise _RpcFail({"name": "HANDLER_ERROR", "cause": {"name": "INVALID_TRANSACTION"},
                            "data": {"TxExecutionError": {"InvalidTxError": {"InvalidNonce": {}}}}})
        self.keys[k] = tx["nonce"]
        self.sent.append(tx)
        result = self._execute(tx)
        self.txs[tx["hash"]] = result
        if self.drop_responses:
            self.drop_responses -= 1
            return _TIMEOUT
        return result

    def _execute(self, tx):
        a = tx["actions"][0]
        receipts, status = [], None
        try:
            value, logs, failures = self.model.call(tx["signer_id"], tx["receiver_id"], a["method"], a["args"])
            receipts.append(_receipt(tx["receiver_id"], logs, {"SuccessValue": ""}))
            for f in failures:
                receipts.append(_receipt(self.model.ids["nft"], [], _failure(f)))
            status = {"SuccessValue": base64.b64encode(jsonlib.dumps(value).encode()).decode()
                      if value is not None else ""}
        except Panic as exc:
            receipts.append(_receipt(tx["receiver_id"], [], _failure(str(exc))))
            status = _failure(str(exc))
        return {"status": status,
                "transaction": {"hash": tx["hash"], "signer_id": tx["signer_id"], "public_key": tx["public_key"],
                                "receiver_id": tx["receiver_id"], "nonce": tx["nonce"],
                                "actions": [{"FunctionCall": {"method_name": a["method"],
                                                              "args": base64.b64encode(near_tx.args_bytes(a["args"])).decode(),
                                                              "gas": a["gas"], "deposit": str(a["deposit"])}}]},
                "transaction_outcome": {"id": tx["hash"], "outcome": {"logs": [], "gas_burnt": 2 * 10 ** 12,
                                                                      "status": {"SuccessReceiptId": "r"},
                                                                      "executor_id": tx["signer_id"]}},
                "receipts_outcome": receipts}

    def _EXPERIMENTAL_tx_status(self, p):
        res = self.txs.get(p["tx_hash"])
        if res is None:
            raise _RpcFail({"name": "HANDLER_ERROR", "cause": {"name": "UNKNOWN_TRANSACTION"}})
        return res

    _tx = _EXPERIMENTAL_tx_status


def _receipt(executor, logs, status):
    rid = hashlib.sha256((executor + jsonlib.dumps(logs)).encode()).hexdigest()[:16]
    return {"id": rid, "outcome": {"executor_id": executor, "logs": logs, "gas_burnt": 5 * 10 ** 12, "status": status}}


def _failure(msg):
    return {"Failure": {"ActionError": {"index": 0, "kind": {"FunctionCallError": {"ExecutionError": f"Smart contract panicked: {msg}"}}}}}


class _RpcFail(Exception):
    def __init__(self, data):
        self.data = data


_TIMEOUT = object()
