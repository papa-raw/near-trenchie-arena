#!/usr/bin/env python3
"""test_readme_steps.py: README.md's make test and rehearsal output match their commands.

  python3 -B near/tools/test_readme_steps.py

Step 7's replay hash changes whenever the default rules table does, and the README's copy of it had gone stale twice.
This case runs the step's own command, `make rehearsal` in near/ (into a temporary folder instead of near/.demo), and
compares its five lines with the five the README shows: the echoed command with only the output folder swapped, and the
other four exactly, the hash included. A wrong hash in the README fails here, naming both.
Step 1 uses copied Makefiles and command stubs to check Cargo present/missing/failing and the documented final line,
without running any Python or Rust suite."""
import os
import re
import shutil
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


class Step1MakeTest(unittest.TestCase):
    def test_contracts_are_optional_and_the_readme_last_line_still_matches(self):
        """Exercise the real Makefiles with command stubs: no Python or Rust suite is launched."""
        make = shutil.which("make")
        self.assertIsNotNone(make, "make is required for the README command")
        with open(README, encoding="utf-8") as f:
            blocks = fences(step(f.read(), 1))
        expected = blocks[blocks.index(["make test"]) + 1]
        skipped = "contracts: cargo not found, skipped (cargo test --workspace runs the contract tests)"
        with tempfile.TemporaryDirectory(prefix="readme-make-") as out:
            near = os.path.join(out, "near")
            contracts = os.path.join(near, "contracts")
            commands = os.path.join(out, "commands")
            os.makedirs(contracts)
            os.makedirs(commands)
            shutil.copyfile(os.path.join(ROOT, "Makefile"), os.path.join(out, "Makefile"))
            shutil.copyfile(os.path.join(ROOT, "near", "Makefile"), os.path.join(near, "Makefile"))
            python = os.path.join(commands, "python-check")
            with open(python, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(python, 0o755)
            env = dict(os.environ, PATH=commands, PY=python, MAKE=make)
            for key in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL"):
                env.pop(key, None)

            def run():
                return subprocess.run([make, "--no-print-directory", "test"], cwd=out, env=env,
                                      capture_output=True, text=True, timeout=30)

            absent = run()
            self.assertEqual(absent.returncode, 0, absent.stdout + absent.stderr)
            self.assertEqual(absent.stdout.splitlines().count(skipped), 1,
                             "make test must explicitly report that contract tests were skipped")
            self.assertEqual(absent.stdout.strip().splitlines()[-1:], expected,
                             "README's make test last line changed")

            cargo = os.path.join(commands, "cargo")
            with open(cargo, "w", encoding="utf-8") as f:
                f.write('#!/bin/sh\nprintf "contracts-cargo: %s" "$PWD"\nprintf " %s" "$@"\nprintf "\\n"\nexit "${CONTRACT_TEST_EXIT:-0}"\n')
            os.chmod(cargo, 0o755)
            present = run()
            self.assertEqual(present.returncode, 0, present.stdout + present.stderr)
            invocation = "contracts-cargo: " + os.path.realpath(contracts) + " test --workspace"
            self.assertEqual(present.stdout.splitlines().count(invocation), 1,
                             "cargo must run once, in near/contracts, with test --workspace")
            self.assertNotIn(skipped, present.stdout)
            self.assertEqual(present.stdout.strip().splitlines()[-1:], expected,
                             "README's make test last line changed")

            env["CONTRACT_TEST_EXIT"] = "7"
            failed = run()
            self.assertNotEqual(failed.returncode, 0, "a failing cargo test must fail make test")
            self.assertIn(invocation, failed.stdout)
            self.assertNotIn(skipped, failed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
