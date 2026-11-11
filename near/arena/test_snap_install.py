"""The documented local install covers host imports and reports connection failures accurately."""
import ast
import errno
from pathlib import Path
import re
import sys
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def local_module(name: str, source: Path) -> tuple[bool, list[Path]]:
    # The host adds these local source directories to its import path.
    for parent in (ROOT, source.parent, ROOT / 'near/arena', ROOT / 'near/house', ROOT / 'near/lore'):
        path = parent.joinpath(*name.split('.'))
        if path.with_suffix('.py').is_file():
            return True, [path.with_suffix('.py')]
        if path.is_dir():
            initial = path / '__init__.py'
            return True, [initial] if initial.is_file() else []
    return False, []


def imported_names(node: ast.AST, source: Path) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    package = source.relative_to(ROOT).parts[:-1]
    prefix = package[:len(package) - node.level + 1] if node.level else ()
    module = '.'.join((*prefix, *(node.module.split('.') if node.module else [])))
    return [module, *(module + '.' + alias.name for alias in node.names if alias.name != '*')]


def host_dependencies() -> set[str]:
    pending, seen, external = [ROOT / 'near/arena/snap_local.py'], set(), set()
    while pending:
        source = pending.pop().resolve()
        if source in seen:
            continue
        seen.add(source)
        for node in ast.walk(ast.parse(source.read_text())):
            for name in imported_names(node, source):
                root = name.split('.')[0]
                if not root or root in sys.stdlib_module_names:
                    continue
                local, files = local_module(name, source)
                if local:
                    pending.extend(files)
                elif not local_module(root, source)[0]:
                    external.add(root)
    return external


def installed_projects(path: Path) -> set[str]:
    pending, seen, projects = [path], set(), set()
    while pending:
        current = pending.pop().resolve()
        if not current.is_relative_to(ROOT):
            raise ValueError('requirements include must stay inside the checkout')
        if current in seen:
            continue
        seen.add(current)
        for raw in current.read_text().splitlines():
            line = raw.split('#', 1)[0].strip()
            if line.startswith('-r '):
                pending.append(current.parent / line[3:].strip())
            elif line:
                projects.add(re.split(r'[<>=!~\[]', line, maxsplit=1)[0].lower().replace('-', '_'))
    return projects


class SnapInstall(unittest.TestCase):
    def test_dev_install_covers_every_third_party_host_import(self) -> None:
        dev = (ROOT / 'near/SNAP.md').read_text().split('## Local snap-in (dev)', 1)[1]
        command = re.search(r'python3 -m pip install -r\s+(\S+)', dev)
        self.assertIsNotNone(command, 'the DEV route needs a requirements install command')
        required = host_dependencies()
        self.assertTrue({'jsonschema', 'cryptography'} <= required, 'follow both host schema and signing imports')
        installed = installed_projects(ROOT / command.group(1))
        self.assertEqual(required - installed, set(), 'DEV requirements omit a third-party host import')


class SnapConnectionErrors(unittest.TestCase):
    def test_permission_failure_names_the_denial_instead_of_suggesting_a_stopped_host(self) -> None:
        sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
        import snap
        denied = urllib.error.URLError(PermissionError(errno.EPERM, 'Operation not permitted'))
        with patch.object(snap.urllib.request, 'urlopen', side_effect=denied), self.assertRaises(SystemExit) as caught:
            snap.call('http://127.0.0.1:8765/dev/terms')
        message = str(caught.exception)
        self.assertIn('Operation not permitted', message)
        self.assertIn('operating system or network policy', message)
        self.assertNotIn('Is snap_local.py running?', message)

    def test_refused_connection_keeps_its_distinct_error(self) -> None:
        sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
        import snap
        refused = urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, 'Connection refused'))
        with patch.object(snap.urllib.request, 'urlopen', side_effect=refused), self.assertRaises(SystemExit) as caught:
            snap.call('http://127.0.0.1:8765/dev/terms')
        self.assertIn('Connection refused', str(caught.exception))
        self.assertNotIn('operating system or network policy', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
