"""NEAR JSON-RPC over `requests` (never urllib: it truncates large bodies through the lane proxy).

`Rpc` takes a list of endpoints and falls through them in order; a rate limit backs off and retries the
same endpoint once, then moves on. A rate limit is an HTTP 429 or a JSON-RPC error body that says so (code -429,
cause TOO_MANY_REQUESTS, or "rate limit" / "too many requests" in its text): rpc.testnet.near.org answers some calls with -429 "deprecated".
A send that is rate limited goes to the next endpoint as the same signed bytes (same hash and nonce), never re-signed;
a send that times out is never re-sent here (its outcome is unknown, and the writer settles it by hash). The transport is injectable (`post=`), so the fake RPC drives this exact code.
`outcome()` turns a `send_tx` / `tx` result into one plain dict the writer acts on.
"""

import base64
import json
import time

import requests

TESTNET_RPC = ["https://rpc.testnet.near.org", "https://rpc.testnet.fastnear.com"]
TESTNET_ARCHIVAL = ["https://archival-rpc.testnet.near.org", "https://archival-rpc.testnet.fastnear.com"]


_NEXT = object()


class RpcError(Exception):
    """The node answered with an error object. `data` is that object, verbatim."""

    def __init__(self, data):
        super().__init__(json.dumps(data)[:600])
        self.data = data

    @property
    def name(self):
        cause = (self.data or {}).get("cause") or {}
        return cause.get("name") or (self.data or {}).get("name")


def rate_limited(error) -> bool:
    """A JSON-RPC error object that is a rate limit, not an answer: the request was not processed."""
    if not isinstance(error, dict):
        return False
    if error.get("code") == -429 or (error.get("cause") or {}).get("name") == "TOO_MANY_REQUESTS":
        return True
    # only the node's own words: a real error whose data quotes "rate limit" (a contract's panic text, a log) stays an error
    cause = error.get("cause") or {}
    text = " ".join(str(v) for v in (error.get("message"), cause.get("name"), cause.get("info")) if v).lower()
    return "too many requests" in text or "rate limit" in text or "ratelimit" in text


class RpcUnreachable(Exception):
    """No endpoint gave an answer: the outcome of a send is unknown."""


class Rpc:
    """`urls` take every call; `read_urls` (default: the same) also serve reads, so a rate-limited node
    (429) passes reads to the next one. A signed transaction goes only to `urls`."""

    def __init__(self, urls, *, read_urls=None, post=None, timeout=90, sleep=time.sleep, rounds=3, attempts=2):
        self.urls = list(urls)
        self.read_urls = list(read_urls) if read_urls else list(urls)
        self.post = post or requests.post
        self.timeout = timeout
        self.sleep = sleep
        self.rounds = rounds
        self.attempts = attempts

    def call(self, method, params, urls=None):
        last = None
        for round_ in range(self.rounds):
            for url in urls or (self.urls if method == "send_tx" else self.read_urls):
                result = self._one(url, method, params, round_)
                if result is not _NEXT:
                    return result
                last = self._last
        raise RpcUnreachable(last)

    def _one(self, url, method, params, round_):
        for attempt in range(self.attempts):
            try:
                r = self.post(url, json={"jsonrpc": "2.0", "id": "chain", "method": method, "params": params},
                              timeout=self.timeout)
            except requests.RequestException as exc:
                self._last = f"{url}: {type(exc).__name__}: {exc}"
                if method == "send_tx":      # the node may have taken it: report unknown, never send it again here
                    raise RpcUnreachable(self._last)
                return _NEXT
            if r.status_code == 429:
                self._last = f"{url}: 429"
                self.sleep(2 * (round_ + 1) * (attempt + 1))
                continue
            try:
                body = r.json()
            except ValueError:
                self._last = f"{url}: HTTP {r.status_code}, not JSON"
                return _NEXT
            if "error" in body:
                if rate_limited(body["error"]):
                    self._last = f"{url}: rate limited: {json.dumps(body['error'])[:200]}"
                    self.sleep(2 * (round_ + 1) * (attempt + 1))
                    continue
                raise RpcError(body["error"])
            return body["result"]
        return _NEXT

    def view(self, account_id, method, args=None):
        res = self.call("query", {"request_type": "call_function", "finality": "final", "account_id": account_id,
                                  "method_name": method,
                                  "args_base64": base64.b64encode(json.dumps(args or {}).encode()).decode()})
        if "error" in res:
            raise RpcError({"name": "VIEW_ERROR", "cause": {"name": "CONTRACT_EXECUTION_ERROR"}, "data": res["error"]})
        return json.loads(bytes(res["result"]).decode() or "null")

    def access_key(self, account_id, public_key):
        return self.call("query", {"request_type": "view_access_key", "finality": "final", "account_id": account_id,
                                   "public_key": public_key})

    def send(self, signed_b64):
        return self.call("send_tx", {"signed_tx_base64": signed_b64, "wait_until": "FINAL"})

    def tx(self, tx_hash, sender):
        return self.call("EXPERIMENTAL_tx_status", {"tx_hash": tx_hash, "sender_account_id": sender, "wait_until": "FINAL"})


def _failure_text(failure) -> str:
    """The panic message inside a NEAR Failure object, or the object itself as compact JSON."""
    try:
        err = failure["ActionError"]["kind"]["FunctionCallError"]
        return err.get("ExecutionError") or json.dumps(err)
    except (KeyError, TypeError):
        return json.dumps(failure, separators=(",", ":"))


def outcome(res: dict) -> dict:
    """{landed, ok, value, failure, receipt_failures, logs, events, tgas} from a final tx result."""
    status = res["status"]
    logs, failures, burnt = [], [], 0
    for o in [res["transaction_outcome"]] + res["receipts_outcome"]:
        oc = o["outcome"]
        logs += oc.get("logs", [])
        burnt += int(oc.get("gas_burnt", 0))
        st = oc.get("status")
        if isinstance(st, dict) and "Failure" in st:
            failures.append(_failure_text(st["Failure"]))
    events = []
    for line in logs:
        if line.startswith("EVENT_JSON:"):
            try:
                events.append(json.loads(line[len("EVENT_JSON:"):]))
            except ValueError:
                pass
    out = {"landed": True, "ok": isinstance(status, dict) and "SuccessValue" in status, "value": None,
           "failure": None, "receipt_failures": failures, "logs": logs, "events": events,
           "tgas": round(burnt / 1e12, 3)}
    if out["ok"]:
        raw = base64.b64decode(status["SuccessValue"] or "")
        out["value"] = json.loads(raw) if raw else None
    else:
        out["failure"] = _failure_text(status.get("Failure") if isinstance(status, dict) else status)
    return out


def events_named(out: dict, name: str) -> list[dict]:
    return [d for e in out["events"] if e.get("event") == name for d in e.get("data", [])]
