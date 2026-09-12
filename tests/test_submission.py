"""Offline submission fixtures. Docker commands are inspected or mocked, never run."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCAN = runpy.run_path(str(ROOT / 'scripts/scan-archive.py'))
CHECK = runpy.run_path(str(ROOT / 'scripts/check-submission.py'))
VALIDATE = runpy.run_path(str(ROOT / 'scripts/check-manifest.py'))['check_manifest']


def archive_at(path, files):
    with tarfile.open(path, 'w:gz') as archive:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = json.loads((ROOT / 'manifests/titanium-tiiny-bot.json').read_text())

    def scan(self, files, permissions=None):
        manifest = copy.deepcopy(self.manifest)
        if permissions is not None:
            manifest['permissions'] = permissions
        archive = archive_at(self.root / 'fixture.tar.gz', files)
        return SCAN['scan_archive'](archive, manifest)

    def test_hidden_secret_and_undeclared_socket_fail(self):
        token = 'ghp_' + 'A' * 36
        result = self.scan({'seed/lite/__main__.py': 'import socket\n',
                            'seed/.hidden': token}, [])
        self.assertFalse(result['ok'])
        self.assertEqual({f['kind'] for f in result['findings']}, {'secret', 'permission'})
        self.assertIn('socket', result['imports'])
        self.assertNotIn(token, json.dumps(result))

    def test_lite_archive_shapes_pass_with_network_declared(self):
        # Match Lite's package structure without its forbidden subprocess helper.
        for wrapper in ('', 'titanium-tiiny-bot-0.1.9/'):
            with self.subTest(wrapper=wrapper):
                result = self.scan({wrapper + 'lite/__init__.py': '',
                                    wrapper + 'lite/__main__.py': 'from . import server\n',
                                    wrapper + 'lite/server.py': 'import socket\nimport http.server\n',
                                    wrapper + 'lite/voice.py': 'headers = {"Authorization": "Bearer " + key}\n'},
                                   ['network', 'microphone'])
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['microphone'], 'declared')

    def test_secret_families_and_chunk_boundary(self):
        samples = ['AKIA' + 'A' * 16, 'github_pat_' + 'b' * 40,
                   'sk-proj-' + 'c' * 32, 'Bearer ' + 'd' * 32,
                   '-----BEGIN RSA PRIVATE KEY-----']
        for token in samples:
            with self.subTest(family=token[:8]):
                result = self.scan({'.config': ' ' * 65530 + token})
                self.assertFalse(result['ok'])
                self.assertNotIn(token, json.dumps(result))

    def test_forbidden_calls_and_import_aliases(self):
        cases = ['import subprocess as sp', 'from subprocess import run',
                 'import ctypes', 'from os import system as launch\nlaunch("x")',
                 'import os as operating\noperating.system("x")', 'eval("1")',
                 'import builtins as b\nb.exec("x")', 'exec("x")',
                 'import importlib\nimportlib.import_module("socket")']
        for code in cases:
            with self.subTest(code=code):
                self.assertFalse(self.scan({'app.py': code})['ok'])

    def test_network_imports_and_parse_failure(self):
        for code in ('from socket import socket', 'import urllib.request', 'from urllib import request', 'import requests', 'def :'):
            self.assertFalse(self.scan({'app.py': code}, [])['ok'])
        self.assertTrue(self.scan({'app.py': 'import json\n'}, [])['ok'])

    def test_traversal_and_links_rejected(self):
        archive = archive_at(self.root / 'bad.tar.gz', {'../escape.py': ''})
        with self.assertRaises(Exception):
            SCAN['scan_archive'](archive, self.manifest)
        self.assertFalse((self.root.parent / 'escape.py').exists())
        with tarfile.open(archive, 'w:gz') as tar:
            member = tarfile.TarInfo('link')
            member.type = tarfile.SYMTYPE
            member.linkname = '/tmp'
            tar.addfile(member)
        with self.assertRaises(Exception):
            SCAN['scan_archive'](archive, self.manifest)

    def test_bundled_lite_truthfully_flags_shell(self):
        bundle = ROOT / 'farm-lite-patch/titanium-tiiny-bot-0.1.9.tar.gz'
        if not bundle.exists():
            self.skipTest('Optional local Lite release archive is not part of a clean checkout')
        result = SCAN['scan_archive'](bundle, self.manifest)
        self.assertFalse(result['ok'])
        self.assertTrue(any(f['kind'] == 'shell' for f in result['findings']))
        self.assertFalse(any(f['kind'] == 'secret' for f in result['findings']))


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'manifests').mkdir()
        self.manifest = json.loads((ROOT / 'manifests/titanium-tiiny-bot.json').read_text())
        # These tests isolate archive/CI behavior; owner gate has its own fixtures below.
        self.owner_patch = patch.dict(CHECK['check_one'].__globals__, check_owner=lambda manifest: True)
        self.owner_patch.start()
        self.addCleanup(self.owner_patch.stop)
        self.manifest['selfcheck'] = False
        self.path = self.root / 'manifests/titanium-tiiny-bot.json'
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.manifest))

    def test_selection_handles_nul_paths_and_rename_destinations(self):
        raw = b'manifests/new.json\0manifests/name with spaces.json\0manifests/new.json\0'
        with patch('subprocess.check_output', return_value=raw) as command:
            self.assertEqual(CHECK['changed_manifests'](self.root, 'a' * 40, 'b' * 40),
                             ['manifests/name with spaces.json', 'manifests/new.json'])
        arguments = command.call_args.args[0]
        self.assertIn('a' * 40 + '...' + 'b' * 40, arguments)
        self.assertIn('--no-renames', arguments)
        self.assertIn('--diff-filter=ACMT', arguments)
        self.assertEqual(arguments[-2:], ['--', 'manifests/'])
        with patch('subprocess.check_output', return_value=b''):
            self.assertEqual(CHECK['changed_manifests'](self.root, 'base', 'head'), [])

    def test_selection_on_divergent_branches_rename_delete_and_spaces(self):
        # A temporary repository makes PR merge-base behavior observable.
        apple_git = Path('/Library/Developer/CommandLineTools/usr/bin/git')
        git = str(apple_git) if apple_git.exists() else shutil.which('git')
        self.assertIsNotNone(git)

        def run(*args):
            return subprocess.check_output([git, '-C', str(self.root), *args], stderr=subprocess.DEVNULL).decode().strip()

        run('init', '-b', 'main')
        run('config', 'user.email', 'fixture@example.invalid')
        run('config', 'user.name', 'Fixture')
        run('add', '.')
        run('commit', '-m', 'Create isolated test fixture')
        common = run('rev-parse', 'HEAD')
        (self.root / 'manifests/base-only.json').write_text('{}')
        run('add', '.')
        run('commit', '-m', 'Advance base branch for selection test')
        base = run('rev-parse', 'HEAD')
        run('checkout', '-b', 'submission', common)
        self.path.rename(self.root / 'manifests/renamed.json')
        (self.root / 'manifests/with space.json').write_text('{}')
        (self.root / 'README.md').write_text('irrelevant')
        run('add', '.')
        run('commit', '-m', 'Exercise manifest rename and addition selection')
        head = run('rev-parse', 'HEAD')
        with patch.dict(os.environ, {'PATH': str(Path(git).parent) + os.pathsep + os.environ['PATH']}):
            self.assertEqual(CHECK['changed_manifests'](self.root, base, head),
                             ['manifests/renamed.json', 'manifests/with space.json'])

    def test_pending_rejected_before_download(self):
        self.manifest['release']['sha256'] = 'pending'
        self.write()
        rows = []
        with patch.object(CHECK['Farm'], 'download') as download:
            CHECK['check_one'](self.root, 'manifests/' + self.path.name, rows)
        download.assert_not_called()
        self.assertEqual(rows[0]['result'], 'FAIL')

    def test_sprouting_skips_archive_checks_after_schema_and_owner(self):
        del self.manifest['release']
        self.manifest['selfcheck'] = True
        self.write()
        for owner_valid in (True, False):
            rows = []
            with self.subTest(owner_valid=owner_valid), patch.object(CHECK['Farm'], 'download') as download, patch.dict(
                    CHECK['check_one'].__globals__, check_owner=lambda _: owner_valid,
                    scan_tree=lambda *_: self.fail('Sprouting seed was scanned'),
                    run_selfcheck=lambda *_: self.fail('Sprouting seed was executed')):
                CHECK['check_one'](self.root, 'manifests/' + self.path.name, rows)
            download.assert_not_called()
            checks = {r['check'].split(': ')[-1]: r['result'] for r in rows}
            self.assertEqual(checks['schema'], 'PASS')
            self.assertEqual(checks['Tiiny owner'], 'PASS' if owner_valid else 'FAIL')
            if owner_valid:
                for check in ('download', 'archive', 'static scan', 'selfcheck'):
                    self.assertEqual(checks[check], 'SKIP')
            else:
                self.assertNotIn('download', checks)

    def test_sprouting_schema_failure_still_blocks_submission(self):
        del self.manifest['release']
        del self.manifest['version']
        self.write()
        rows = []
        with patch.object(CHECK['Farm'], 'download') as download:
            CHECK['check_one'](self.root, 'manifests/' + self.path.name, rows)
        download.assert_not_called()
        self.assertEqual(rows[0]['result'], 'FAIL')

    def test_workflow_only_prepares_image_for_release_selfchecks(self):
        workflow = (ROOT / '.github/workflows/manifest-check.yml').read_text()
        source = workflow.split("python3 - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
        source = '\n'.join(line[10:] for line in source.splitlines())
        self.assertIn("if: steps.selfchecks.outputs.needed == 'true'", workflow)
        self.assertIn('Validate submissions and TiinyVerse ownership', workflow)
        release = self.manifest['release']
        for has_release, selfcheck, expected in ((False, True, 'false'), (True, False, 'false'), (True, True, 'true')):
            with self.subTest(has_release=has_release, selfcheck=selfcheck):
                self.manifest.pop('release', None)
                if has_release:
                    self.manifest['release'] = release
                self.manifest['selfcheck'] = selfcheck
                self.write()
                output = self.root / 'workflow-output'
                output.write_text('')
                # An absolute selection keeps this fixture independent of the workflow checkout path.
                selection = {'changed_manifests': lambda *_: [str(self.path)]}
                with patch('runpy.run_path', return_value=selection), patch.dict(os.environ, {
                        'BASE_SHA': 'base', 'HEAD_SHA': 'head', 'GITHUB_OUTPUT': str(output)}):
                    exec(compile(source, 'manifest-check workflow', 'exec'), {})
                self.assertEqual(output.read_text(), f'needed={expected}\n')

    def test_identity_and_duplicate_fail(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                other = self.root / 'manifests/other.json'
                if duplicate:
                    other.write_text(self.path.read_text())
                    relative = 'manifests/' + self.path.name
                else:
                    relative = 'manifests/other.json'
                    other.write_text(self.path.read_text())
                rows = []
                with patch.object(CHECK['Farm'], 'download') as download:
                    CHECK['check_one'](self.root, relative, rows)
                download.assert_not_called()
                self.assertEqual(rows[-1]['result'], 'FAIL')

    def test_download_hash_size_scan_end_to_end(self):
        archive = archive_at(self.root / 'fixture.tar.gz', {'release/lite/__main__.py': 'import socket\n'})
        data = archive.read_bytes()
        self.manifest['release'].update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        self.write()
        for mutation in (None, 'sha256', 'size'):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.manifest)
                if mutation == 'sha256':
                    changed['release']['sha256'] = '0' * 64
                elif mutation == 'size':
                    changed['release']['size'] += 1
                self.path.write_text(json.dumps(changed))
                rows = []
                with patch('farm.farm.urlopen', return_value=io.BytesIO(data)):
                    CHECK['check_one'](self.root, 'manifests/' + self.path.name, rows)
                self.assertEqual(any(r['result'] == 'FAIL' for r in rows), mutation is not None, rows)

    def test_red_scan_blocks_declared_selfcheck(self):
        archive = archive_at(self.root / 'bad.tar.gz', {'lite/__main__.py': 'import subprocess'})
        data = archive.read_bytes()
        self.manifest['release'].update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        self.manifest['selfcheck'] = True
        self.write()
        rows = []
        with patch('farm.farm.urlopen', return_value=io.BytesIO(data)), patch.dict(
                CHECK['check_one'].__globals__, run_selfcheck=lambda *_: self.fail('Unsafe app was executed')):
            CHECK['check_one'](self.root, 'manifests/' + self.path.name, rows)
        self.assertTrue(any(r['result'] == 'FAIL' for r in rows))
        self.assertEqual(rows[-1]['result'], 'SKIP')

    def test_selfcheck_schema_and_offline_command(self):
        self.manifest['selfcheck'] = True
        VALIDATE(self.manifest)
        command = CHECK['selfcheck_command'](self.manifest, self.root, 'test-container')
        self.assertEqual(command[command.index('--network') + 1], 'none')
        self.assertIn('python:3.11-slim', command)
        self.assertEqual(command[-1], '--selfcheck')
        self.assertIn('--read-only', command)
        self.manifest['entry'] = None
        self.manifest['tags'] = ['library']
        with self.assertRaises(ValueError):
            VALIDATE(self.manifest)
        self.manifest['selfcheck'] = 'true'
        with self.assertRaises(ValueError):
            VALIDATE(self.manifest)

    def test_selfcheck_exit_and_timeout_are_mocked(self):
        for exit_code in (0, 1):
            with patch('subprocess.run', return_value=subprocess.CompletedProcess([], exit_code)) as run:
                self.assertEqual(CHECK['run_selfcheck'](self.manifest, self.root), exit_code == 0)
                self.assertEqual(run.call_args_list[0].kwargs['timeout'], 120)
                self.assertEqual(run.call_args_list[-1].args[0][:3], ['docker', 'rm', '-f'])
        with patch('subprocess.run', side_effect=[subprocess.TimeoutExpired('mock', 120), subprocess.CompletedProcess([], 0)]):
            self.assertFalse(CHECK['run_selfcheck'](self.manifest, self.root))

    def test_site_install_and_guide_links(self):
        site = runpy.run_path(str(ROOT / 'scripts/build-site.py'))
        self.assertIn('pip install tiinyapp-farm', site['steps']())
        self.assertIn('farm device', site['steps']())
        self.assertIn('/docs/SUBMIT.md', site['page']('Submit an app', site['seeds'](), '/submit/'))


class OwnerGateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / 'manifests/titanium-tiiny-bot.json').read_text())
        self.manifest['author']['tiinyverse'] = 'https://www.tiinyverse.com/users/39628b1e-e94e-4bd8-800e-5437d5336e1f'

    def response(self, value):
        response = io.BytesIO(json.dumps(value).encode())
        response.status = 200
        response.url = 'https://tiinyapp.farm/api/owners?profile=fixture'
        return response

    def test_verified_owner_required_studio_name_allowed(self):
        for verified, name, expected in ((True, self.manifest['author']['name'], True),
                                          (False, self.manifest['author']['name'], False),
                                          (True, 'Studio or other display name', True)):
            with patch.dict(CHECK['check_owner'].__globals__, urlopen=lambda *a, **k: self.response({'verified': verified, 'name': name})):
                self.assertEqual(CHECK['check_owner'](self.manifest), expected)
        del self.manifest['author']['tiinyverse']
        self.assertFalse(CHECK['check_owner'](self.manifest))

    def test_unavailable_gate_fails_closed_before_archive_download(self):
        with patch.dict(CHECK['check_owner'].__globals__, urlopen=lambda *a, **k: (_ for _ in ()).throw(TimeoutError())):
            self.assertFalse(CHECK['check_owner'](self.manifest))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifests').mkdir()
            path = root / 'manifests' / (self.manifest['id'] + '.json')
            path.write_text(json.dumps(self.manifest))
            rows = []
            with patch.dict(CHECK['check_one'].__globals__, check_owner=lambda _: False), patch.object(CHECK['Farm'], 'download') as download:
                CHECK['check_one'](root, 'manifests/' + path.name, rows)
            download.assert_not_called()
            self.assertEqual(rows[-1]['check'], 'manifests/' + path.name + ': Tiiny owner')
            self.assertEqual(rows[-1]['detail'], 'The seed must name a verified TiinyVerse owner.')


if __name__ == '__main__':
    unittest.main()
