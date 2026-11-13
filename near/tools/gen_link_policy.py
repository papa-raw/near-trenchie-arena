"""Mirror the host's link policy into the standalone creator; use --check to detect drift.

Edit near/house/link_policy.json, then run python3 -I near/tools/gen_link_policy.py.
The creator needs no fetch or extra script before it can validate a name.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / 'near/house/link_policy.json'
SHEET = ROOT / 'near/web/snapin/sheet.js'
START = '  // BEGIN GENERATED LINK POLICY\n'
END = '  // END GENERATED LINK POLICY'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        policy = json.loads(POLICY.read_text(encoding='ascii'))
        source = SHEET.read_text()
        if source.count(START) != 1 or source.count(END) != 1:
            raise ValueError('sheet.js needs exactly one generated link-policy block')
        before, rest = source.split(START)
        _, after = rest.split(END)
        block = '  // Generated from near/house/link_policy.json; run near/tools/gen_link_policy.py.\n'
        block += '  var LINK_POLICY = ' + json.dumps(policy, separators=(',', ':')) + ';\n'
        wanted = before + START + block + END + after
        if args.check:
            if wanted != source:
                raise ValueError('creator link policy is stale; run python3 -I near/tools/gen_link_policy.py')
        elif wanted != source:
            SHEET.write_text(wanted)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'link policy: {exc}\n')


if __name__ == '__main__':
    main()
