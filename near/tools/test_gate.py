#!/usr/bin/env python3
"""Cases for near/tools/gate.py. Each builds a throwaway git repo, plants a hit built from pieces (so this file
holds none of the strings its subject looks for), runs the gate on it with throwaway pattern files, and checks
the exit code and the printed counts.

  python3 -B near/tools/test_gate.py
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

GATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gate.py")
ROOM_FILES = ["__init__.py", "service.py", "protocol.py", "protocol.schema.json", "slots.py", "identity.py",
              "policy.py", "ledger.py", "results.py", "bridge.py", "ROOM.md", "requirements.txt",
              "test_room.py", "test_identity.py", "test_policy.py", "test_recovery.py", "mutants.py"]
NAMES = [f"Person{chr(65 + i)} Surname{chr(65 + i)}" for i in range(14)]
COMMIT = "0123456789abcdef0123456789abcdef01234567"
GITIGNORE = ".env\n.env.*\n*.env\n*.pem\n*.key\nnode_modules/\n__pycache__/\n"
BANNED_A = "jud" + "ge"
BANNED_B = "figur" + "e"
REL = "release 0.2." + "19"
INT = "arti" + "facts/"


def w(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(text)


def git(root, *args):
    subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@invalid", *args], check=True,
                   capture_output=True)


class Fixture:
    """A repo plus a pattern-file folder, both in a temp dir."""

    def __init__(self, test):
        self.tmp = tempfile.TemporaryDirectory(prefix="gate-case-")
        test.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "repo")
        self.cfg = os.path.join(self.tmp.name, "cfg")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        w(os.path.join(self.repo, ".gitignore"), GITIGNORE)
        w(os.path.join(self.repo, "README.md"), "A plain readme.\n")
        w(os.path.join(self.repo, "room-source.json"), '{"commit": "%s"}\n' % COMMIT)
        for f in ROOM_FILES:
            w(os.path.join(self.repo, "room", f), f"room file {f}\n")
            w(os.path.join(self.cfg, "room-src", f), f"room file {f}\n")
        w(os.path.join(self.cfg, "room-src.commit"), COMMIT + "\n")
        w(os.path.join(self.cfg, "names.txt"), "\n".join(NAMES) + "\n")
        w(os.path.join(self.cfg, "deny.txt"), "# comment\nforbidden-word-xyz\n")
        w(os.path.join(self.cfg, "leak.txt"), r"internal-folder/|\bT-[0-9]{2}\b|\b0\.2\.19\b" + "\n")

    def put(self, rel, text):
        w(os.path.join(self.repo, rel), text)

    def commit(self):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "fixture")

    def run(self, *args, env=None):
        e = {k: v for k, v in os.environ.items() if not k.startswith("TRENCHIE_")}
        e["TRENCHIE_GATE_DIR"] = self.cfg
        e.update(env or {})
        r = subprocess.run([sys.executable, "-I", GATE, "--root", self.repo, *args], capture_output=True, text=True, env=e)
        return r.returncode, r.stdout + r.stderr

    def counts(self, out):
        return {m.group(1).strip(): int(m.group(2)) for m in re.finditer(r"^(\w[\w ]*?)\s*: (\d+) lines$", out, re.M)}


class GateScans(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture(self)

    def run_scans(self, **kw):
        return self.fx.run("--no-clean-clone", **kw)

    def test_clean_tree_prints_zero_for_every_scan_with_date_and_count(self):
        self.fx.commit()
        code, out = self.run_scans()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.fx.counts(out), {"private sweep": 0, "names sweep": 0, "client deny scan": 0,
                                               "leak check": 0, "room copy": 0})
        self.assertRegex(out, r"gate 20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ .*files=\d+")

    def test_each_scan_catches_a_planted_hit_and_names_it(self):
        planted = {
            "private sweep": ("a.py", "tok = '" + "gh" + "p_" + "a" * 36 + "'\n"),
            "names sweep": ("b.md", f"A {BANNED_A} said so.\n"),
            "client deny scan": ("c.md", "text with forbidden-word-xyz in it\n"),
            "leak check": ("d.md", "see internal-folder/notes\n"),
        }
        for label, (rel, text) in planted.items():
            with self.subTest(scan=label):
                fx = Fixture(self)
                fx.put(rel, text)
                fx.commit()
                code, out = fx.run("--no-clean-clone")
                self.assertEqual(code, 1, out)
                self.assertGreaterEqual(fx.counts(out)[label], 1, out)
                self.assertIn(rel, out)

    def test_private_hit_never_prints_the_whole_secret(self):
        secret = "gh" + "p_" + "Q" * 36
        self.fx.put("a.py", f"tok = '{secret}'\n")
        self.fx.commit()
        code, out = self.run_scans()
        self.assertEqual(code, 1)
        self.assertNotIn(secret, out)

    def test_private_catches_machine_paths_key_files_internal_folders_and_missing_ignore_rules(self):
        self.fx.put("x.md", "see /" + "Users" + "/someone/notes\n")
        self.fx.put("keys/deploy.pem", "not a real key\n")
        self.fx.put(INT + "plan.md", "internal\n")
        self.fx.put(".gitignore", ".env\n")
        self.fx.commit()
        code, out = self.run_scans()
        self.assertEqual(code, 1)
        for want in ("x.md:1", "keys/deploy.pem", INT + "plan.md", "missing pattern *.pem"):
            self.assertIn(want, out)

    def test_names_catch_a_full_name_in_text_and_in_a_file_name_but_not_a_first_name_alone(self):
        self.fx.put("n1.md", "Met PersonC SurnameC today.\n")
        self.fx.put("PersonD SurnameD.txt", "plain\n")
        self.fx.put("n2.md", "PersonE alone, and Surname alone\n")
        self.fx.put(f"{BANNED_B}.txt", "plain\n")
        self.fx.commit()
        code, out = self.run_scans()
        self.assertEqual(code, 1)
        self.assertIn("n1.md:1", out)
        self.assertIn("PersonD SurnameD.txt", out)
        self.assertIn(f"{BANNED_B}.txt", out)
        self.assertNotIn("n2.md", out)

    def test_look_alikes_pass(self):
        self.fx.put("ok.md", f"{BANNED_A}d, {BANNED_A.upper()}ment? no. {BANNED_A}ing and re{BANNED_B}d. NEP-141, P-256, SHA-256.\n")
        self.fx.commit()
        code, out = self.run_scans()
        self.assertEqual(code, 0, out)

    def test_an_untracked_file_is_scanned_and_an_ignored_one_is_not(self):
        self.fx.commit()
        self.fx.put("new.md", f"a {BANNED_A} here\n")
        self.fx.put("__pycache__/x.pyc", f"a {BANNED_A} here\n")
        code, out = self.run_scans()
        self.assertEqual(code, 1)
        self.assertIn("new.md:1", out)
        self.assertNotIn("__pycache__", out)
        self.assertIn("1 untracked", out)

    def test_release_number_is_allowed_only_in_the_build_log(self):
        self.fx.put("BUILD-LOG.md", REL + " ships the room.\n")
        self.fx.commit()
        code, out = self.run_scans()
        self.assertEqual(code, 0, out)
        self.fx.put("README.md", REL + " ships the room.\n")
        code, out = self.run_scans()
        self.assertEqual(code, 1)
        self.assertIn("README.md:1", out)
        self.assertNotIn("BUILD-LOG.md:1", out)

    def test_room_copy_flags_changed_missing_and_extra_files_and_a_wrong_commit(self):
        self.fx.put("room/service.py", "edited\n")
        os.remove(os.path.join(self.fx.repo, "room", "ledger.py"))
        self.fx.put("room/helper.py", "extra\n")
        self.fx.put("room-source.json", '{"commit": "%s"}\n' % ("f" * 40))
        self.fx.commit()
        code, out = self.run_scans()
        self.assertEqual(code, 1)
        for want in ("room/service.py:0:bytes differ", "room/ledger.py:0:missing from the copy",
                     "room/helper.py:0:file not in the room allowlist", "room-source.json:0:names a commit"):
            self.assertIn(want, out)
        self.assertEqual(self.fx.counts(out)["room copy"], 4)

    def test_a_missing_pattern_file_is_loud_and_exits_2(self):
        self.fx.commit()
        for name, word in (("names.txt", "NAMES FILE MISSING"), ("deny.txt", "DENY FILE MISSING"),
                           ("leak.txt", "LEAK FILE MISSING")):
            with self.subTest(name=name):
                fx = Fixture(self)
                fx.commit()
                os.remove(os.path.join(fx.cfg, name))
                code, out = fx.run("--no-clean-clone")
                self.assertEqual(code, 2, out)
                self.assertIn(word, out)
                self.assertIn("NOT RUN", out)

    def test_a_missing_room_source_and_a_short_names_list_exit_2(self):
        self.fx.commit()
        os.remove(os.path.join(self.fx.cfg, "room-src.commit"))
        code, out = self.run_scans()
        self.assertEqual((code, "ROOM SOURCE UNDATED" in out), (2, True), out)
        fx = Fixture(self)
        fx.commit()
        w(os.path.join(fx.cfg, "names.txt"), "Only One\n")
        code, out = fx.run("--no-clean-clone")
        self.assertEqual((code, "NAMES FILE SHORT" in out), (2, True), out)

    def test_the_gate_source_passes_its_own_private_and_names_scans(self):
        fx = Fixture(self)
        with open(GATE, "rb") as f:
            w(os.path.join(fx.repo, "near/tools/gate.py"), f.read().decode(), "w")
        fx.commit()
        code, out = fx.run("--no-clean-clone", "private", "names")
        self.assertEqual(code, 0, out)


class CleanClone(unittest.TestCase):
    MAKE_OK = ("test:\n\t@echo tests ok\n"
               "demo:\n\t@echo 'NOT BUILT: demo'; exit 2\n"
               "live:\n\t@echo 'NOT BUILT: live'; exit 2\n")

    def setUp(self):
        self.fx = Fixture(self)

    def test_a_passing_test_and_two_stubs_exit_0_and_the_stubs_are_called_not_built(self):
        self.fx.put("Makefile", self.MAKE_OK)
        self.fx.commit()
        code, out = self.fx.run("clean-clone")
        self.assertEqual(code, 0, out)
        self.assertIn("make test passed from a fresh clone", out)
        self.assertIn("make demo is NOT BUILT", out)
        self.assertIn("make live is NOT BUILT", out)
        self.assertEqual(self.fx.counts(out), {"clean clone": 0})

    def test_a_failing_test_is_a_hit_with_the_tail_of_its_output(self):
        self.fx.put("Makefile", "test:\n\t@echo boom reason; exit 1\ndemo:\n\t@exit 0\nlive:\n\t@exit 0\n")
        self.fx.commit()
        code, out = self.fx.run("clean-clone")
        self.assertEqual(code, 1, out)
        self.assertIn("clean-clone: make test:0:exit", out)
        self.assertIn("boom reason", out)

    def test_a_stub_that_exits_0_is_reported_as_passed_not_as_not_built(self):
        self.fx.put("Makefile", self.MAKE_OK.replace("exit 2", "exit 0"))
        self.fx.commit()
        code, out = self.fx.run("clean-clone")
        self.assertEqual(code, 0, out)
        self.assertIn("make demo passed from a fresh clone", out)
        self.assertNotIn("is NOT BUILT", out)

    def test_uncommitted_changes_make_the_run_refuse(self):
        self.fx.put("Makefile", self.MAKE_OK)
        self.fx.commit()
        self.fx.put("later.md", "uncommitted\n")
        code, out = self.fx.run("clean-clone")
        self.assertEqual(code, 1, out)
        self.assertIn("uncommitted", out)

    def test_a_path_entry_that_names_a_harness_checkout_makes_the_run_refuse(self):
        self.fx.put("Makefile", self.MAKE_OK)
        self.fx.commit()
        bad = os.path.join(self.fx.tmp.name, "co" + "harness", "bin")
        os.makedirs(bad)
        code, out = self.fx.run("clean-clone", env={"PATH": bad + os.pathsep + os.environ["PATH"]})
        self.assertEqual(code, 1, out)
        self.assertIn("harness checkout", out)

    def test_the_clone_gets_no_pythonpath(self):
        self.fx.put("Makefile", "test:\n\t@test -z \"$$PYTHONPATH\" && echo path-clean\n"
                    "demo:\n\t@exit 0\nlive:\n\t@exit 0\n")
        self.fx.commit()
        code, out = self.fx.run("clean-clone", env={"PYTHONPATH": "/somewhere"})
        self.assertEqual(code, 0, out)
        self.assertIn("path-clean", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
