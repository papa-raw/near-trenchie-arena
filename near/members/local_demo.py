"""Interactive local rehearsal; synthetic proofs only, real copied room and engine."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'near/arena'), str(Path(__file__).resolve().parent)]
from near.members.member_fixture import MemberCases
from near.members.runtime import member_server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--proposal', action='store_true', help='Create a real local proposal with two other synthetic member answers.')
    mode.add_argument('--unpublished', action='store_true', help='Use an authoritative unpublished checkpoint (synthetic local room).')
    options = parser.parse_args()
    host = MemberCases(published=not options.unpublished)
    if options.proposal:
        host.reset(proposal=True)
    server = member_server(host.session)
    print('Synthetic local rehearsal: no wallet service, model provider or chain.', flush=True)
    print(f'http://127.0.0.1:{server.server_port}/#'+('change' if options.proposal else 'terms'), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return
    finally:
        server.server_close()
        host.close()


if __name__ == '__main__':
    main()
