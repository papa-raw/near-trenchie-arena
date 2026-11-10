"""Loopback page adapter for one owner's proved SnapClient; no house credentials."""
from __future__ import annotations

from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
import uuid

from near.arena.snap_client import SnapClient, SnapRefusal
from room.policy import validate

ASSETS = Path(__file__).resolve().parent
MAX_BODY = 4096


class MemberSession:
    """Owner-runtime port, supplied by the game's own admission/wallet adapter.

    Only this owner's client may be installed. Tokens, proofs and signing keys
    stay behind this loopback boundary. The browser sends explicit self-consent
    choices with the exact version it read. An uncertain write is never retried.
    A fresh authenticated snapshot resolves it. No moderator API is exposed.
    room_label is an optional trusted local display label for the pinned room.
    """

    def __init__(self, client: SnapClient | None, *, connect: Callable[[], SnapClient] | None = None,
                 public_client: SnapClient | None = None, room_label: str | None = None) -> None:
        self.client, self.connect, self.public_client = client, connect, public_client
        self.room_label = room_label
        self.lock = threading.RLock()

    def _view(self, snapshot: dict) -> dict:
        clock = self.client.observe()["clock"]
        return dict(snapshot=snapshot, wallet_connected=True, can_answer=self.client.can_answer,
                    room_label=self.room_label or snapshot["name"], current_segment_id=clock["segment_id"])

    def _public(self) -> dict | None:
        if self.public_client is None:
            return None
        try:
            manifest, clock = self.public_client.manifest(), self.public_client.observe()["clock"]
            return dict(input_interval_ms=manifest["limits"]["intent_interval_ms"],
                        segment_ms=str(clock["segment_seconds"] * 1000), simulation_hz=clock["tick_hz"])
        except (OSError, ValueError):
            return None

    def read(self) -> dict:
        with self.lock:
            if self.client is None:
                return dict(error="wallet_disconnected", public_terms=self._public(), wallet_connected=False,
                            room_label=self.room_label)
            return self._view(self.client.member_snapshot(request_id="view-" + uuid.uuid4().hex))

    def failure(self, error: str) -> dict:
        """Keep trusted display context without asserting private authentication."""
        with self.lock:
            return dict(error=error, room_label=self.room_label,
                        wallet_connected=False if self.client is None else None,
                        public_terms=self._public())

    def write(self, request: dict) -> dict:
        with self.lock:
            action = request.get("action")
            if not isinstance(action, str):
                raise SnapRefusal("bad_message")
            if action == "connect":
                if set(request) != {"action"} or self.connect is None:
                    raise SnapRefusal("wallet_unavailable")
                self.client = self.connect()
                return self.read()
            if self.client is None:
                raise SnapRefusal("wallet_disconnected")
            snapshot = self._answer(action, request)
            return self._view(snapshot)

    def _answer(self, action: str, request: dict) -> dict:
        expected = {"action", "terms_version"}
        if action in {"accept_change", "decline_change"}:
            expected.add("proposal_id")
        if set(request) != expected:
            raise SnapRefusal("bad_message")
        validate("U64", request["terms_version"])
        request_id = "answer-" + uuid.uuid4().hex
        if action == "accept_terms":
            return self.client.accept_terms(request["terms_version"], request_id=request_id)
        if action in {"accept_change", "decline_change"}:
            validate("Id", request["proposal_id"])
            return self.client.answer_change(request["proposal_id"], request["terms_version"],
                accept=action == "accept_change", request_id=request_id)
        raise SnapRefusal("bad_message")


class MemberHandler(BaseHTTPRequestHandler):
    """Same-origin loopback ingress; static paths never expose runtime code."""

    session: MemberSession

    def log_message(self, format: str, *args: object) -> None:
        return  # Private requests and signed state do not enter HTTP logs.

    def reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def json_reply(self, status: int, value: dict) -> None:
        self.reply(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _origin(self) -> bool:
        expected = "http://127.0.0.1:" + str(self.server.server_port)
        origin = self.headers.get("Origin")
        return (self.headers.get("Host") == expected.removeprefix("http://")
                and origin in (None, expected) and self.headers.get("Sec-Fetch-Site") != "cross-site")

    def do_GET(self) -> None:
        if not self._origin():
            self.json_reply(403, {"error": "proof_required"})
            return
        target = urlsplit(self.path).path
        if target == "/api/member":
            self._call(self.session.read)
            return
        target = "/index.html" if target == "/" else target
        types = {"/index.html": "text/html; charset=utf-8", "/page.js": "text/javascript; charset=utf-8",
                 "/style.css": "text/css; charset=utf-8", "/arena.png": "image/png"}
        if target == "/fonts/" + Path(target).name and Path(target).name in {
                "Fredoka-var.woff2", "LilitaOne-400.woff2", "SpaceMono-400.woff2", "SpaceMono-700.woff2"}:
            types[target] = "font/woff2"
        if target not in types:
            self.json_reply(404, {"error": "not_found"})
            return
        try:
            body = (ASSETS / target.lstrip("/")).read_bytes()
        except OSError:
            self.json_reply(503, {"error": "recovery_pending"})
            return
        self.reply(200, body, types[target])

    def do_POST(self) -> None:
        if (not self._origin() or self.path != "/api/member"
                or self.headers.get("X-Member-Action") != "explicit"
                or self.headers.get("Content-Type") != "application/json"):
            self.json_reply(403, {"error": "proof_required"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                raise ValueError("bounded request required")
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise ValueError("object required")
        except (ValueError, UnicodeError):
            self.json_reply(400, {"error": "bad_message"})
            return
        self._call(lambda: self.session.write(request), write=True)

    def _call(self, operation: Callable[[], dict], *, write: bool = False) -> None:
        try:
            value = operation()
        except SnapRefusal as exc:
            self.json_reply(409, self.session.failure(str(exc)))
            return
        except (OSError, TimeoutError):
            self.json_reply(503, self.session.failure("answer_uncertain" if write else "room_unavailable"))
            return
        except ValueError:
            self.json_reply(503, self.session.failure("room_unavailable"))
            return
        self.json_reply(200, value)


def member_server(session: MemberSession, *, port: int = 0,
                  handler_class: type[MemberHandler] = MemberHandler) -> ThreadingHTTPServer:
    """Create a loopback-only server for one owner's existing admission client."""
    class BoundHandler(handler_class):
        pass
    BoundHandler.session = session
    return ThreadingHTTPServer(("127.0.0.1", port), BoundHandler)
