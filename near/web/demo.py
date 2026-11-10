"""Generate one synthetic SNAP rehearsal archive with the real room and engine."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]

from near.web.evidence import read_evidence
from portable_records import EngineRecords
from test_room_host import CopiedRoom
from test_snap_cold import ColdHost, SnapCold


def generate(output: Path) -> dict:
    """Run SNAP's exact isolated program; export native public fixture material.

    Reuses fixture transport/process helpers, never an existing test method.
    HMAC authority, identities, rival and clock are synthetic; room and engine
    are the real local implementations. No wallet, model or chain is called.
    """
    snap = (ROOT / 'near/SNAP.md').read_text()
    match = re.search(r'<!-- BEGIN COLD AGENT -->\s*```python\n(.*?)\n```\s*<!-- END COLD AGENT -->', snap, re.S)
    if match is None:
        raise ValueError('SNAP executable program missing')
    case, runner = CopiedRoom(), SnapCold()
    case.setUp()
    try:
        with tempfile.TemporaryDirectory(prefix='desk-owner-') as temporary:
            owner, public = runner.prepare_owner(Path(temporary), snap, match.group(1))
            result_context = copy.deepcopy(case.context)
            result_context['audience'] = 'near:mainnet:' + result_context['contract_ids']['arena'] + ':post_batch'
            records = EngineRecords(case.arena.store, Path(case.tmp.name) / 'wire.sqlite',
                case.context, result_context, key_id='room_key_a', sign=case.sign,
                verify=lambda key, body, signature: signature == case.sign(body),
                key_allowed=lambda key: key == 'room_key_a')
            host = ColdHost(case, records)
            boot = dict(public_checkout=str(public), context=case.context, result_context=result_context,
                session_public_key=case.example('SessionPublicKey'), now_ms=case.now,
                account_id='alice.near', nft_token_id='alice', persona_digest=hashlib.sha256(b'alice').hexdigest())
            summary, _ = runner.run_agent(owner, boot, host)
            if not all(summary[key] for key in ('terms_accepted', 'combat_seen', 'ko_seen', 'signed_result')):
                raise ValueError('SNAP rehearsal did not reach a signed fight result')
            if summary['prediction_lock'] != summary['public_lock']:
                raise ValueError('agent/public forecast lock mismatch')
            output.mkdir(parents=True, exist_ok=True)
            archive = case.arena.store.segment('segment:0')
            (output / 'segment.json').write_text(json.dumps(archive, sort_keys=True) + '\n')
            facts = read_evidence(output)
            if facts['state'] != 'checked':
                raise ValueError('generated archive failed its replay check')
            (output / 'evidence.json').write_text(json.dumps(facts, indent=2) + '\n')
            return facts
    finally:
        runner.doCleanups()
        case.doCleanups()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'near/.demo')
    args = parser.parse_args()
    try:
        facts = generate(args.output)
    except (OSError, ValueError, AssertionError, KeyError) as exc:
        parser.exit(1, 'Local demo refused: ' + str(exc) + '\n')
    print('Synthetic local run: no model, wallet, hosted service or chain.')
    print('Replay checked locally: ' + facts['recorded_hash'])
    print('Chain check pending. Public full forecast and score remain pending.')
    print('Open the desk: make -C near desk')


if __name__ == '__main__':
    main()
