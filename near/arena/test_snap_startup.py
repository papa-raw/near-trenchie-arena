"""Missing startup dependencies produce one complete installation hint."""
from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

CLIENT = Path(__file__).resolve().with_name('snap.py')
REQUIREMENTS = CLIENT.parents[1] / 'requirements.txt'
ISOLATED = '''
import importlib.abc
import runpy
import sys

client, missing, command = sys.argv[1:]
class HideDependency(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if missing and (fullname == missing or fullname.startswith(missing + '.')):
            raise ModuleNotFoundError("No module named " + repr(fullname), name=fullname)
sys.meta_path.insert(0, HideDependency())
for name in tuple(sys.modules):
    if missing and (name == missing or name.startswith(missing + '.')):
        del sys.modules[name]
sys.argv = [client, command]
runpy.run_path(client, run_name='__main__')
'''


class SnapStartup(unittest.TestCase):
    def run_client(self, missing: str, command: str = 'terms', *, client: Path = CLIENT) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            return subprocess.run([sys.executable, '-I', '-B', '-c', ISOLATED, str(client), missing, command],
                                  cwd=directory, capture_output=True, text=True, timeout=15)

    def test_missing_jsonschema_has_one_complete_install_hint(self) -> None:
        result = self.run_client('jsonschema')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr.splitlines(),
                         [f'Missing jsonschema: run python3 -m pip install -r {shlex.quote(str(REQUIREMENTS))}'])

    def test_missing_cryptography_uses_the_same_complete_install(self) -> None:
        result = self.run_client('cryptography')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr.splitlines(),
                         [f'Missing cryptography: run python3 -m pip install -r {shlex.quote(str(REQUIREMENTS))}'])

    def test_scratch_directory_hint_names_an_existing_absolute_file(self) -> None:
        result = self.run_client('jsonschema')
        prefix = 'Missing jsonschema: run python3 -m pip install -r '
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.startswith(prefix))
        arguments = shlex.split(result.stderr.removeprefix(prefix).strip())
        self.assertEqual(len(arguments), 1)
        requirements = Path(arguments[0])
        self.assertTrue(requirements.is_absolute())
        self.assertTrue(requirements.is_file())
        self.assertEqual(requirements, REQUIREMENTS)

    def test_checkout_path_with_spaces_pastes_as_one_shell_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "Agent's checkout space"
            client = root / 'near/arena/snap.py'
            client.parent.mkdir(parents=True)
            client.write_text(CLIENT.read_text())
            requirements = root / 'near/requirements.txt'
            requirements.touch()
            result = self.run_client('cryptography', client=client)
            prefix = 'Missing cryptography: run '
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, '')
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertTrue(result.stderr.startswith(prefix))
            command = result.stderr.removeprefix(prefix).strip()
            shell = subprocess.run(['/bin/sh', '-c', 'set -- ' + command + '; printf "%s\\n" "$@"'],
                                   cwd=directory, capture_output=True, text=True, timeout=15)
            self.assertEqual(shell.returncode, 0, shell.stderr)
            self.assertEqual(shell.stderr, '')
            self.assertEqual(shell.stdout.splitlines(),
                             ['python3', '-m', 'pip', 'install', '-r', str(requirements)])

    def test_missing_repository_modules_keep_the_normal_traceback(self) -> None:
        for missing in ('near', 'dev_persona', 'presets'):
            with self.subTest(missing=missing):
                result = self.run_client(missing)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertIn('Traceback (most recent call last):', result.stderr)
                self.assertIn('ModuleNotFoundError: No module named ' + repr(missing), result.stderr)
                self.assertNotIn('pip install', result.stderr)

    def test_installed_dependencies_keep_the_cli_available(self) -> None:
        result = self.run_client('', '--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('usage:', result.stdout)
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
