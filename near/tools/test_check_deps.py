#!/usr/bin/env python3
"""Cases for near/tools/check_deps.py.  python3 -B near/tools/test_check_deps.py"""
import os
import subprocess
import sys
import tempfile
import unittest

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_deps.py")


def run(*args):
    r = subprocess.run([sys.executable, "-I", TOOL, *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


class CheckDeps(unittest.TestCase):
    def reqs(self, text, extra=None):
        d = tempfile.TemporaryDirectory(prefix="deps-case-")
        self.addCleanup(d.cleanup)
        p = os.path.join(d.name, "requirements.txt")
        with open(p, "w") as f:
            f.write(text)
        for name, body in (extra or {}).items():
            with open(os.path.join(d.name, name), "w") as f:
                f.write(body)
        return p

    def test_a_package_at_its_pinned_version_passes(self):

        self.assertEqual(run(self.reqs("pip==%s\n" % self._pip_version()))[0], 0)

    def _pip_version(self):
        from importlib import metadata
        return metadata.version("pip")

    def test_a_missing_package_fails_loudly_and_says_how_to_fix_it(self):
        code, out = run(self.reqs("no-such-package-xyz==1.0\n"))
        self.assertEqual(code, 1)
        self.assertIn("MISSING no-such-package-xyz==1.0", out)
        self.assertIn("make setup", out)

    def test_a_wrong_version_fails_and_names_the_installed_one(self):
        code, out = run(self.reqs("pip==0.0.1\n"))
        self.assertEqual(code, 1)
        self.assertIn("WRONG   pip==0.0.1 (installed " + self._pip_version() + ")", out)

    def test_nested_requirement_files_are_followed(self):
        code, out = run(self.reqs("-r inner.txt\n", {"inner.txt": "no-such-package-xyz==2.0  # comment\n"}))
        self.assertEqual(code, 1)
        self.assertIn("no-such-package-xyz==2.0", out)

    def test_an_unpinned_line_is_refused(self):
        code, out = run(self.reqs("pip>=1\n"))
        self.assertNotEqual(code, 0)
        self.assertIn("cannot read the line", out)

    def test_the_trees_own_pins_are_read(self):
        code, out = run()
        self.assertIn("jsonschema==4.26.0", out)
        self.assertIn("cryptography==46.0.7", out)

    def test_a_constraints_file_is_followed_and_its_pins_bind_only_what_is_installed(self):
        # -c pins a dependency's version without asking for it: absent is fine (pip installs it only when needed,
        # e.g. typing-extensions below Python 3.13); installed at another version is a failure.
        code, out = run(self.reqs("-c constraints.txt\n", {"constraints.txt": "no-such-package-xyz==1.0\n"}))
        self.assertEqual(code, 0, out)
        self.assertIn("unused  no-such-package-xyz==1.0", out)
        code, out = run(self.reqs("-c constraints.txt\n", {"constraints.txt": "pip==0.0.1\n"}))
        self.assertEqual(code, 1)
        self.assertIn("WRONG   pip==0.0.1 (installed " + self._pip_version() + ")", out)

    def test_the_trees_constraints_pin_every_dependency_of_the_three_pinned_packages(self):
        code, out = run()
        for pin in ("certifi==2026.7.22", "urllib3==2.6.3", "referencing==0.37.0", "rpds-py==0.30.0", "cffi==2.0.0",
                    "pycparser==3.0", "attrs==26.1.0", "idna==3.13", "charset-normalizer==3.4.7",
                    "jsonschema-specifications==2025.9.1", "typing-extensions==4.15.0"):
            self.assertIn(pin, out)


if __name__ == "__main__":
    unittest.main()
