#!/usr/bin/env python3
"""test_readme_steps.py: README.md's "Do X, see Y" output for step 7 is what step 7's command prints today.

  python3 -B near/tools/test_readme_steps.py

Step 7's replay hash changes whenever the default rules table does, and the README's copy of it had gone stale twice.
This case runs the step's own command, `make rehearsal` in near/ (into a temporary folder instead of near/.demo), and
compares its five lines with the five the README shows: the echoed command with only the output folder swapped, and the
other four exactly, the hash included. A wrong hash in the README fails here, naming both."""
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
README = os.path.join(ROOT, "README.md")


def step(text, number):
    """The text of numbered step `number` in the "Do X, see Y" list, up to the next numbered step or heading."""
    m = re.search(rf"^{number}\. .*?(?=^\d+\. |^#)", text, re.S | re.M)
    if m is None:
        raise AssertionError(f"README.md has no step {number}.")
    return m.group(0)


def fences(block):
    """Every fenced block's lines in a step, indentation removed."""
    return [[line.strip() for line in body.strip("\n").splitlines()]
            for body in re.findall(r"^\s*```[a-z]*\n(.*?)^\s*```", block, re.S | re.M)]


class Step7Rehearsal(unittest.TestCase):
    def test_the_readme_shows_what_make_rehearsal_prints(self):
        with open(README, encoding="utf-8") as f:
            command, expected = fences(step(f.read(), 7))[:2]
        self.assertEqual(command, ["(cd near && make rehearsal)"], "step 7's command changed: update this case with it")
        with tempfile.TemporaryDirectory(prefix="readme-step7-") as out:
            run = subprocess.run(["make", "--no-print-directory", "rehearsal", f"DEMO_DIR={out}"],
                                 cwd=os.path.join(ROOT, "near"), capture_output=True, text=True, timeout=300)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            printed = run.stdout.strip("\n").splitlines()
            printed[0] = printed[0].replace(f'"{out}"', '".demo"')
        self.assertEqual(printed, expected,
                         "README.md step 7 no longer matches `(cd near && make rehearsal)`; put the printed lines "
                         "(the replay hash above all) into the README")


if __name__ == "__main__":
    unittest.main(verbosity=2)
