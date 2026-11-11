#!/usr/bin/env python3
"""play_local.py: everything for a local click-through, from one command (`make play`), stopped by Ctrl-C.

  python3 -B near/tools/play_local.py [--live] [--arena-port 8765] [--web-port 8181] [--house keyed|dev] [--budget building]
  make play            (keyless)          make play LIVE=1     (the live house, on the model key)

It starts, from the repo root:
  1. the DEV arena host, near/arena/snap_local.py, with the house:
       keyed  the default: no key and no model calls, ever; the house posts its keyed lines (deterministic).
              A NEARAI_API_KEY already in the shell is kept out of the host. It says so in one line.
       live   only with --live (make play LIVE=1): the 14 personas on the NEAR AI Cloud model. The key comes from
              NEARAI_API_KEY or ~/.config/trenchie/nearai.env, goes into the host's environment only and is never
              printed; the file's path and the day's cap are printed before anything starts.
     and TRENCHIE_BLOCKLIST from ~/.config/trenchie/blocklist.json when that file exists (else every feed line is
     muted to an emote and the host prints "guard list missing");
  2. the same-origin web server, near/web/snapin/serve.py, which serves the pages and passes the room's routes through;
then prints the URLs (the arena page, the snap-in guide) and the SNAP.md commands an agent session runs.
Ctrl-C (or SIGTERM) stops both and waits for them; if either one exits on its own, the other is stopped and the
reason printed. Loopback only. Nothing is left running.
"""
from __future__ import annotations

import argparse
import http.client
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path.home() / ".config" / "trenchie"
KEY_ENV = "NEARAI_API_KEY"


def read_key(path: Path) -> str | None:
    """The model key from an env file (KEY=VALUE lines), or None. The value is never printed."""
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if line.startswith(KEY_ENV + "="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def port_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def answers(port: int, path: str) -> bool:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}", "Connection": "close"})
        resp = conn.getresponse()
        resp.read()                 # read it all: closing on unread bytes resets the socket and the server logs a traceback
        conn.close()
        return resp.status == 200
    except OSError:
        return False


def day_cap(mode: str):
    """The live house's daily cap in USD for a budget mode, read from near/house/runtime.py (not imported)."""
    import ast
    src = (ROOT / "near/house/runtime.py").read_text()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DAY_CAPS_USD" for t in node.targets):
            return ast.literal_eval(node.value).get(mode)
    return None


def plan(args, environ: dict) -> tuple[list, dict, list]:
    """(the host's argv, the host's environment, the lines to print about what was chosen). No process started.

    The model key is used only with --live: without it no key reaches the host, whatever the shell holds."""
    env = dict(environ)
    notes = []
    env.pop(KEY_ENV, None)
    if args.live:
        house = "live"
        keyfile = CONFIG / "nearai.env"
        source = "the NEARAI_API_KEY environment variable" if environ.get(KEY_ENV) else str(keyfile)
        if not environ.get(KEY_ENV) and keyfile.exists() and keyfile.stat().st_mode & 0o077:
            raise SystemExit(f"play: {keyfile} is readable by others; fix it with: chmod 600 {keyfile}")
        key = environ.get(KEY_ENV) or read_key(keyfile)
        if not key:
            raise SystemExit(f"play: --live needs {KEY_ENV} set, or a {KEY_ENV}= line in {CONFIG / 'nearai.env'}")
        cap = day_cap(args.budget)
        env[KEY_ENV] = key
        notes.append(f"house: LIVE, the 14 personas on NEAR AI Cloud; key from {source} (not printed); "
                     f"daily cap ${cap} ({args.budget}), then the house goes on autopilot")
    else:
        house = args.house
        notes.append(f"house: keyless, {'its keyed lines' if house == 'keyed' else 'the plain DEV house'}, no model "
                     f"calls (make play LIVE=1 for the live house)")
    blocklist = CONFIG / "blocklist.json"
    if env.get("TRENCHIE_BLOCKLIST"):
        notes.append("guard: block list from TRENCHIE_BLOCKLIST")
    elif blocklist.exists():
        env["TRENCHIE_BLOCKLIST"] = str(blocklist)
        notes.append(f"guard: block list {blocklist}")
    else:
        notes.append("guard list missing: every feed line is muted to an emote (put the list at " + str(blocklist) + ")")
    argv = [sys.executable, "-B", str(ROOT / "near/arena/snap_local.py"), "--port", str(args.arena_port),
            "--house", house, "--budget", args.budget]
    return argv, env, notes


def agent_lines(arena_port: int, web_port: int) -> list[str]:
    url = "" if arena_port == 8765 else f" --url http://127.0.0.1:{arena_port}"
    snap = f'python3 -I "$R/near/arena/snap.py"{url}'
    return [
        "Agent door (a Claude Code or Codex session): give it this, from an empty folder outside the checkout:",
        f'  "Read {ROOT}/near/SNAP.md, section Local snap-in (dev), and snap into the arena at http://127.0.0.1:{arena_port}."',
        "Or by hand, in an empty scratch folder (make your sheet as SNAP.md shows):",
        f"  export R={ROOT}",
        f"  {snap} terms",
        f"  {snap} join --sheet <your-sheet>.json --preset hunter --accept-terms 1 --spread 40,30,20,10 --zero 10",
        f'  {snap} intent --focus nearest --sig auto --say "One ripple at a time."',
        f"  {snap} result --wait 90",
        f"  {snap} stop",
        f"Pair a browser AI door instead: open the guide, pick the Claude Code door, then  {snap} join --code <CODE> --preset hunter --accept-terms 1",
    ]


def stop(procs: list) -> None:
    for p in procs:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    end = time.monotonic() + 8
    for p in procs:
        try:
            p.wait(timeout=max(0.1, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arena-port", type=int, default=8765)
    ap.add_argument("--web-port", type=int, default=8181)
    ap.add_argument("--live", action="store_true", help="the live house on the NEAR AI Cloud key (spends, under the day's cap)")
    ap.add_argument("--house", choices=("keyed", "dev"), default="keyed", help="the keyless house (default keyed)")
    ap.add_argument("--budget", default="building")
    args = ap.parse_args(argv)
    for port in (args.arena_port, args.web_port):
        if not port_free(port):
            raise SystemExit(f"play: port {port} is in use (another arena or server?); stop it or pass another port")
    host_argv, host_env, notes = plan(args, os.environ)
    procs = []
    stopping = {"why": None}

    def on_signal(signum, _frame):
        if not stopping["why"]:
            print(f"\nplay: stopping ({signal.Signals(signum).name}): the arena host and the web server…", flush=True)
        stopping["why"] = signal.Signals(signum).name
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    try:
        procs.append(subprocess.Popen(host_argv, cwd=ROOT, env=host_env, start_new_session=True))
        for line in notes:
            print("play: " + line, flush=True)
        deadline = time.monotonic() + 90
        while not answers(args.arena_port, "/dev/health"):
            if procs[0].poll() is not None:
                raise SystemExit(f"play: the arena host exited ({procs[0].returncode}) before it answered; see its lines above")
            if time.monotonic() > deadline or stopping["why"]:
                raise SystemExit("play: the arena host did not answer /dev/health within 90 s" if not stopping["why"] else "play: stopped")
            time.sleep(0.3)
        web_env = {k: v for k, v in os.environ.items() if k != KEY_ENV}      # the web server never sees the key
        procs.append(subprocess.Popen([sys.executable, "-I", str(ROOT / "near/web/snapin/serve.py"), "--port",
                                       str(args.web_port), "--arena", f"http://127.0.0.1:{args.arena_port}"],
                                      cwd=ROOT, env=web_env, start_new_session=True))
        while not answers(args.web_port, "/web/arena.html"):
            if procs[1].poll() is not None:
                raise SystemExit(f"play: the web server exited ({procs[1].returncode}) before it answered")
            if stopping["why"]:
                raise SystemExit("play: stopped")
            time.sleep(0.3)
        web = f"http://127.0.0.1:{args.web_port}"
        print("\n".join(["", "play: READY",
                         f"  Watch the arena:       {web}/web/arena.html",
                         f"  Snap in (the guide):   {web}/web/snapin/index.html",
                         f"  Host health:           {web}/dev/health", ""] + agent_lines(args.arena_port, args.web_port)
                        + ["", "Ctrl-C stops everything this started.", ""]), flush=True)
        while not stopping["why"]:
            for name, p in zip(("the arena host", "the web server"), procs):
                if p.poll() is not None:
                    stopping["why"] = f"{name} exited ({p.returncode})"
                    break
            time.sleep(0.5)
        if stopping["why"] not in ("SIGINT", "SIGTERM"):
            print(f"play: stopping ({stopping['why']})", flush=True)
        return 0 if stopping["why"] in ("SIGINT", "SIGTERM") else 1
    finally:
        stop(procs)
        print("play: stopped; nothing left running", flush=True)


if __name__ == "__main__":
    sys.exit(main())
