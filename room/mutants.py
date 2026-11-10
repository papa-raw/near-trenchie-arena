"""Named room proof cases and explicitly selected, isolated rule removals.

Listing is read-only. Cases use disposable local fixtures; they certify neither
an engine integration nor a deployment. Mutation replay requires a passing case
receipt for the exact source bytes. Missing cases and skipped tests are not passes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
S = 'room.test_room.NamedServiceProof.'
L = 'room.test_room.NamedLedgerProof.'
R = 'room.test_recovery.RecoveryCases.'
I = 'room.test_identity.IdentityCases.'
P = 'room.test_policy.PolicyCases.'
V = 'room.test_room.RoomServiceCases.'


def check(cases=(), *needs):
    return dict(cases=tuple(cases), needs=tuple(needs))


CHECKS = {
    'ownership': check(('room.test_room.NamedSlotProof.test_slot_authority', S+'test_ownership'), 'Bound engine and two real member connections.'),
    'target': check((S+'test_target',), 'Engine legal enemy attack and owner-only operations.'),
    'clock': check((S+'test_clock',), 'Measure engine at 20 Hz through a complete 1200-tick segment.'),
    'action-cap': check((S+'test_action_cap',), 'Bound engine clock under concurrent member traffic.'),
    'seat-check': check((S+'test_seat_check',), 'Engine seat acknowledgement and live house-fill mismatch.'),
    'reach': check((S+'test_reach',), 'External transport, host filesystem, secret and socket probes.'),
    'result-at-boundary': check((L+'test_result_at_boundary',), 'Actual engine life/segment boundary and interrupted-process run.'),
    'referee-digest': check((L+'test_referee_digest',), 'Separate referee principal replaying archived engine bytes.'),
    'owner-canary-wall': check((P+'test_owner_canary_wall', S+'test_canary_outputs'),
        'Two live owners plus spectator, reconnect, API/status and archived replay probes.'),
    'forged-result': check((R+'test_sealed_result', R+'test_forged_result', R+'test_pending_retry'),
        'Twenty actual engine segments, isolated referee and destination replay rejection.'),
    'private-red-team': check(('room.test_room.ProtocolBoundary.test_exported_parser_and_service_share_wire_rules', S+'test_byte_limit', V+'test_traffic_per_account_and_ip_before_chain_work',
        V+'test_intent_rate_and_slow_reader_bounds', V+'test_ban_reconnect_and_guest_moderation_refusal'),
        'Measured live load/latency, nested and slow sockets, submitted script/package/archive escape probes.'),
    'outside-harness': check((), 'Fresh outside client using only the public connection guide: join, predict, fight, result; malformed/version refusals.'),
    'identity-transfer': check((I+'test_nft_proof_and_custody', I+'test_identity_transfer_and_session_grants',
        I+'test_outage_lock_expiry_and_epoch_close_authority'), 'Live owner/custody, sale/lock and RPC adapter evidence.'),
    'prediction-lock': check((R+'test_prediction_lock', V+'test_resume_keeps_live_body_and_closed_prediction'),
        'Engine activation consumes the durable lock through reconnect and recovery.'),
    'wallet-sale-control': check((I+'test_sale_proof_is_separate_from_play',
        V+'test_offline_sale_lookup_authenticates_without_second_effect'),
        'Game sale state machine: legal exit boundary, transfer and confirmed clearing-batch spawn fence; failed receipts remain pending.'),
    'security-restore-fence': check((R+'test_security_restore_fence', R+'test_pending_retry'),
        'Authenticated off-host journal outside backup rollback scope plus current chain reconciliation.'),
    'signed-context': check((I+'test_signed_context', R+'test_signed_context'),
        'Deployed control, sale, receipt and result consumers with pinned current context.'),
    'restart-and-restore': check((L+'test_restart_and_restore', R+'test_pending_retry'),
        'Real crash/reboot, empty-host restore, intentional stop and interrupted-segment supervision.'),
    'copy-and-leak': check((), 'Private exact-copy exporter, complete committed allowlist, clean destination clone and public-content gates.'),
    'launch-gate': check((), 'Admission controller bound to accepted source/copy/image/config/deployment evidence; missing or failing evidence must keep admission closed.'),
}

DEPLOYED = {
    'Access': 'Probe root/password/public SSH refusal from outside the host.',
    'Network': 'Probe non-public ports, expired/bad TLS and over-limit traffic.',
    'Containers': 'Probe read-only root, escape denial and live resource throttling.',
    'Integrity': 'Submit forged and tampered results to the deployed writer.',
    'Operations': 'Crash restart, intentional stop, real restore and received alert.',
    'Abuse': 'Ban a connected identity, then attempt a fresh reconnect.',
    'Load': 'Capped room load and bounded overload fallback with measured latency.',
    'Review': 'Independent attack against the pinned live deployment.',
    'First fix': 'Externally re-probe historical port 4100 closure.',
}

# id, source path, exact predicate, replacement, focused case, named contract.
# Literal \\n is used in TSV so changed-predicate selection can compare each line.
MUTATIONS = (
    ('slot-authority', 'room/slots.py', 'binding.get(k) != record[k] for k in', 'False for k in', 'room.test_room.NamedSlotProof.test_slot_authority', 'ownership'),
    ('own-fighter', 'room/policy.py', "if fighter_id is None or request['payload']['fighter_id'] != fighter_id:", 'if False:', S+'test_ownership', 'ownership'),
    ('owner-action', 'room/policy.py', "if fighter_id is None or request['payload']['fighter_id'] != fighter_id:", 'if False:', S+'test_target', 'target'),
    ('client-clock', 'room/policy.py', 'if not validator.is_valid(value):', 'if False:', S+'test_clock', 'clock'),
    ('intent-rate', 'room/policy.py', 'if last is not None and now - last < self.intent_interval_ms:', 'if False:', S+'test_action_cap', 'action-cap'),
    ('seat-binding', 'room/service.py', 'if fighter["binding"] != binding or fighter["life_id"] != life_id or fighter["lock_ref"] != lock["lock_ref"]:', 'if False:', S+'test_seat_check', 'seat-check'),
    ('absolute-route', 'room/service.py', 'if parsed.scheme or parsed.netloc or parsed.fragment:', 'if False:', S+'test_reach', 'reach'),
    ('complete-record', 'room/ledger.py', "validate('SealedRecord', record)", 'pass', L+'test_result_at_boundary', 'result-at-boundary'),
    ('sealed-byte', 'room/ledger.py', "if record['sealed_result_hash'] != sealed_hash(record):", 'if False:', L+'test_referee_digest', 'referee-digest'),
    ('independent-replay', 'room/ledger.py', "if (outcome['final_state_hash'] != record['final_state_hash'] or\\n                outcome['lives'] != lives or\\n                prediction_log_hash(events, outcome['predictions']) != record['predictions_log_hash']):", 'if False:', L+'test_referee_digest', 'referee-digest'),
    ('private-projection', 'room/policy.py', "result = _project(_SCHEMA['$defs'][schema_name], value)", 'result = deepcopy(value)', P+'test_owner_canary_wall', 'owner-canary-wall'),
    ('result-signature', 'room/results.py', 'if valid is not True:', 'if False:', R+'test_forged_result', 'forged-result'),
    ('batch-replay', 'room/results.py', "if any(row['kind'] == 'batch' and\\n                   (row['data']['batch_id'] == binding['batch_id'] or\\n                    row['data']['segment_id'] == binding['segment_id']) for row in rows):", 'if False:', R+'test_pending_retry', 'forged-result'),
    ('byte-limit', 'room/protocol.py', 'if len(raw) > max_control_bytes:', 'if False:', S+'test_byte_limit', 'private-red-team'),
    ('join-rate', 'room/service.py', 'if len(values) >= self.limits["join_attempts_per_minute"]:', 'if False:', V+'test_traffic_per_account_and_ip_before_chain_work', 'private-red-team'),
    ('slow-reader', 'room/service.py', 'snapshots=deque(maxlen=self.limits["pending_snapshot_frames"]), private=deque())', 'snapshots=deque(), private=deque())', V+'test_intent_rate_and_slow_reader_bounds', 'private-red-team'),
    ('locked-token', 'room/identity.py', "elif evidence['play_status'] != 'eligible':", 'elif False:', I+'test_nft_proof_and_custody', 'identity-transfer'),
    ('grant-binding', 'room/identity.py', "if request[field] != binding[field]:", 'if False:', I+'test_identity_transfer_and_session_grants', 'identity-transfer'),
    ('prediction-once', 'room/ledger.py', 'if existing is not None:', 'if False:', R+'test_prediction_lock', 'prediction-lock'),
    ('lock-before-start', 'room/ledger.py', "if lock is None or lock['lock_ref'] != lock_ref:", 'if False:', R+'test_prediction_lock', 'prediction-lock'),
    ('sale-owner', 'room/identity.py', "if owner['ownership_kind'] != 'owner' or evidence['sale_control_allowed'] is not True or evidence['play_status'] == 'unknown':", "if evidence['sale_control_allowed'] is not True or evidence['play_status'] == 'unknown':", I+'test_sale_proof_is_separate_from_play', 'wallet-sale-control'),
    ('restored-revocation', 'room/ledger.py', "grant_id not in self.state['revocations'] and", 'True and', R+'test_security_restore_fence', 'security-restore-fence'),
    ('result-context', 'room/results.py', "if message['context'] != self.context:", 'if False:', R+'test_signed_context', 'signed-context'),
    ('backup-integrity', 'room/ledger.py', "if (position != len(rows) or predecessor != previous or digest(row) != record_hash or\\n                        canonical(data).decode() != encoded):", 'if False:', L+'test_restart_and_restore', 'restart-and-restore'),
)


def table():
    return ''.join('\t'.join(row) + '\n' for row in MUTATIONS)


def selected_rows(path):
    rows = list(csv.reader(Path(path).read_text().splitlines(), delimiter='\t', quoting=csv.QUOTE_NONE))
    known = set(MUTATIONS)
    if any(tuple(row) not in known for row in rows) or len({tuple(row) for row in rows}) != len(rows):
        raise ValueError('unknown or duplicate mutation row')
    return rows


def dependencies(case):
    files = ['__init__.py', 'protocol.schema.json', case.rsplit('.', 2)[0].split('.')[-1] + '.py']
    if case.startswith('room.test_room.NamedSlotProof.'):
        files += ['slots.py']
    elif case.startswith((S, V, 'room.test_room.ProtocolBoundary.')):
        files += ['slots.py', 'service.py', 'protocol.py', 'identity.py', 'policy.py']
    elif case.startswith((R, L)):
        files += ['ledger.py', 'results.py', 'test_recovery.py']
    elif case.startswith(I):
        files += ['identity.py', 'policy.py']
    elif case.startswith(P):
        files += ['policy.py']
    return sorted(set(files))


def missing(root, case):
    absent = [filename for filename in dependencies(case) if not (root / 'room' / filename).is_file()]
    if case.startswith((R, L)) and shutil.which('openssl') is None:
        absent.append('openssl with Ed25519 support')
    if not absent and case.startswith((S, V, R, L, I, P)) and importlib.util.find_spec('jsonschema') is None:
        absent.append('pinned jsonschema dependency')
    return absent


def availability(root):
    return [dict(name=name, status='NOT RUN', cases=list(entry['cases']),
                 needs=list(entry['needs']), missing={case: missing(root, case)
                        for case in entry['cases'] if missing(root, case)})
            for name, entry in CHECKS.items()]


def fingerprint(root):
    files = sorted((root / 'room').glob('*.py')) + [root / 'room/protocol.schema.json', root / 'room/requirements.txt']
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return hasher.hexdigest()


def positive(outcome):
    return (outcome.get('tests') == 1 and outcome.get('success') is True and
            not any(outcome.get(key) for key in ('failures', 'errors', 'skipped')))


def detected(outcome, case):
    return (outcome.get('tests') == 1 and outcome.get('success') is False and
            bool(outcome.get('failures')) and
            all(name == case or name.startswith(case + ' (') for name in outcome['failures']) and
            not outcome.get('errors') and not outcome.get('skipped'))


def validate_baseline(root, baseline, cases):
    if baseline.get('fingerprint') != fingerprint(root):
        raise ValueError('baseline source differs; run the selected positive cases on these bytes')
    if any(not positive(baseline.get('cases', {}).get(case, {})) for case in cases):
        raise ValueError('every selected mutation requires its passing, unskipped positive case')
    return baseline


def child(root, case):
    with tempfile.TemporaryDirectory(prefix='room-outcome-') as directory:
        result_file = Path(directory) / 'outcome.json'
        command = [sys.executable, '-B', str(root / 'room/mutants.py'), '--child-case', case,
                   '--result-file', str(result_file)]
        try:
            process = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=45)
            if not result_file.is_file():
                return dict(tests=0, success=False, failures=[], errors=['child did not report'],
                            skipped=[], log=process.stderr)
            result = json.loads(result_file.read_text())
            result['log'] = process.stderr
            return result
        except subprocess.TimeoutExpired:
            return dict(tests=0, success=False, failures=[], errors=['timeout'], skipped=[])


def run_cases(root, names):
    output = dict(fingerprint=fingerprint(root), cases={}, checks={})
    for name in names:
        entry = CHECKS[name]
        blocked = {}
        for case in entry['cases']:
            needs = missing(root, case)
            if needs:
                blocked[case] = needs
            elif case not in output['cases']:
                output['cases'][case] = child(root, case)
        failed = any(not positive(output['cases'][case]) for case in entry['cases'] if case in output['cases'])
        state = ('FAIL' if failed else 'NOT RUN' if blocked or not entry['cases'] else 'PASS')
        output['checks'][name] = dict(status='FAIL' if state == 'FAIL' else 'NOT RUN' if entry['needs'] else state,
            portable_status=state, missing=blocked, needs=list(entry['needs']))
    return output


def cases_exit(output):
    # Full gate needs remain NOT RUN in the receipt even when the portable
    # subset succeeds. A missing executable prerequisite is exit 5, never green.
    states = [entry['portable_status'] for name, entry in output['checks'].items()
              if CHECKS[name]['cases']]
    return 1 if 'FAIL' in states else 5 if not states or 'NOT RUN' in states else 0


def replay(root, rows, baseline):
    validate_baseline(root, baseline, [row[4] for row in rows if not missing(root, row[4])])
    results = []
    for name, path, old, new, case, contract in rows:
        needs = missing(root, case)
        if needs:
            results.append(dict(id=name, status='NOT RUN', needs=needs))
            continue
        source = root / path
        original = source.read_text()
        old, new = old.replace('\\n', '\n'), new.replace('\\n', '\n')
        if original.count(old) != 1:
            results.append(dict(id=name, status='NOT RUN', needs=['predicate must occur exactly once']))
            continue
        with tempfile.TemporaryDirectory(prefix='room-rule-') as directory:
            copied = Path(directory)
            # Only the public package is copied; no checkout, keys or host adapter.
            shutil.copytree(root / 'room', copied / 'room',
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            (copied / path).write_text(original.replace(old, new, 1))
            outcome = child(copied, case)
        results.append(dict(id=name, check=contract, case=case,
                            status='CAUGHT' if detected(outcome, case) else 'NOT CAUGHT', outcome=outcome))
    return results


def child_case(case, result_file):
    if case not in {case for entry in CHECKS.values() for case in entry['cases']}:
        raise ValueError('unlisted case')
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.loadTestsFromName(case)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    # A nested call to an existing fixture method is still one named test.
    output = dict(tests=result.testsRun, success=result.wasSuccessful(),
        failures=[test.id() for test, _ in result.failures],
        errors=[test.id() for test, _ in result.errors], skipped=[test.id() for test, _ in result.skipped])
    Path(result_file).write_text(json.dumps(output) + '\n')
    sys.stderr.write(stream.getvalue())
    return 0 if positive(output) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--list', action='store_true')
    mode.add_argument('--cases', nargs='*', choices=tuple(CHECKS))
    mode.add_argument('--selection', type=Path)
    mode.add_argument('--write-table', type=Path)
    mode.add_argument('--child-case')
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--result-file', type=Path)
    args = parser.parse_args()
    if args.list:
        output = dict(checks=availability(ROOT), deployed={name: dict(status='NOT RUN', need=need)
                                                        for name, need in DEPLOYED.items()})
    elif args.write_table:
        args.write_table.write_text(table())
        return 0
    elif args.child_case:
        if args.result_file is None:
            raise ValueError('--result-file is required')
        return child_case(args.child_case, args.result_file)
    elif args.selection is not None:
        rows = selected_rows(args.selection)
        if not rows:
            output = dict(mutations=[], note='empty selection; no mutation executed')
        else:
            if args.baseline is None:
                raise ValueError('--baseline is required for mutation replay')
            output = dict(mutations=replay(ROOT, rows, json.loads(args.baseline.read_text())))
        print(json.dumps(output, indent=2))
        states = [row['status'] for row in output['mutations']]
        return 1 if 'NOT CAUGHT' in states else 5 if 'NOT RUN' in states else 0
    else:
        output = run_cases(ROOT, args.cases or list(CHECKS))
        if args.receipt:
            args.receipt.write_text(json.dumps(output, indent=2) + '\n')
        print(json.dumps(output, indent=2))
        return cases_exit(output)
    print(json.dumps(output, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        raise SystemExit('room proof: ' + str(exc))
