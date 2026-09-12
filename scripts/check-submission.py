#!/usr/bin/env python3
"""Check changed PR manifests with trusted code; run app code only in Docker in CI."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import shlex
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from farm.farm import Farm  # noqa: E402

scan_tree = runpy.run_path(str(ROOT / 'scripts/scan-archive.py'))['scan_tree']


def changed_manifests(repository, base, head):
    # Disable rename detection: a rename must validate its new destination.
    output = subprocess.check_output(['git', '-C', str(repository), 'diff', '--no-renames',
                                      '--name-only', '--diff-filter=ACMT', '-z', base + '...' + head,
                                      '--', 'manifests/'])
    return sorted({name for name in os.fsdecode(output).split('\0') if name})


def selfcheck_command(manifest, root, name):
    entry = manifest['entry']
    command = (['python', '-m', entry['python'], *entry['args']]
               if 'python' in entry else shlex.split(entry['command']))
    return ['docker', 'run', '--rm', '--name', name, '--network', 'none',
            '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--pids-limit', '64', '--memory', '512m', '--cpus', '1', '--user', '65534:65534',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m', '-e', 'HOME=/tmp',
            '-e', 'PYTHONDONTWRITEBYTECODE=1', '-v', f'{root.resolve()}:/app:ro',
            '-w', '/app', 'python:3.11-slim', *command, '--selfcheck']


def run_selfcheck(manifest, root):
    name = 'farm-selfcheck-' + uuid.uuid4().hex
    try:
        completed = subprocess.run(selfcheck_command(manifest, root, name), timeout=120,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return completed.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    finally:
        subprocess.run(['docker', 'rm', '-f', name], timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def check_owner(manifest):
    """Fail closed; use only the farm origin, never a manifest-supplied endpoint."""
    profile = manifest.get('author', {}).get('tiinyverse')
    if not profile:
        return False
    request = Request('https://tiinyapp.farm/api/owners?' + urlencode({'profile': profile}),
                      headers={'User-Agent': 'tiinyapp-farm-ci/1.0'})
    try:
        with urlopen(request, timeout=10) as response:
            if response.status != 200 or response.url.split('?')[0] != 'https://tiinyapp.farm/api/owners':
                return False
            raw = response.read(4097)
        if len(raw) > 4096:
            return False
        owner = json.loads(raw)
        return owner.get('verified') is True  # the profile is the proof; author.name may be a studio name
    except Exception:
        return False


def check_one(repository, relative, rows):
    def row(check, ok, detail):
        rows.append({'check': f'{relative}: {check}', 'result': 'PASS' if ok else 'FAIL', 'detail': detail})

    path = repository / relative
    try:
        parts = PurePosixPath(relative).parts
        if len(parts) != 2 or parts[0] != 'manifests' or path.suffix != '.json' or path.is_symlink():
            raise ValueError('Manifest must be a regular manifests/<id>.json file')
        # The schema and checker come from the trusted base checkout, never the PR.
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/check-manifest.py'), str(path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        if result.returncode:
            row('schema', False, 'Run scripts/check-manifest.py locally for details; pending releases are refused')
            return
        manifest = json.loads(path.read_text())
        row('schema', True, 'Schema valid; no --allow-pending')
        matches = []
        for other in (repository / 'manifests').rglob('*.json'):
            if other.is_symlink():
                raise ValueError('Symlink manifest refused')
            candidate = json.loads(other.read_text())
            if candidate.get('id') == manifest['id']:
                matches.append(other)
        valid_id = manifest['id'] == path.stem and len(matches) == 1
        row('identity', valid_id, 'ID must match filename and be unique throughout the catalog')
        if not valid_id:
            return
        if not check_owner(manifest):
            row('Tiiny owner', False, 'The seed must name a verified TiinyVerse owner.')
            return
        row('Tiiny owner', True, 'The farm confirmed the TiinyVerse owner')
        if 'release' not in manifest:
            for check in ('download', 'archive', 'static scan', 'selfcheck'):
                rows.append({'check': f'{relative}: {check}', 'result': 'SKIP',
                             'detail': 'Sprouting seed; no release yet'})
            return
        with tempfile.TemporaryDirectory(prefix='farm-submission-') as temporary:
            temp = Path(temporary)
            archive = temp / 'release.tar'
            # Remote catalog policy prevents file:// and local release reads.
            Farm(catalog='https://tiinyapp.farm/manifests/').download(manifest['release'], archive)
            row('download', True, 'Release downloaded; SHA-256 and exact byte size match')
            unpacked = temp / 'unpacked'
            unpacked.mkdir()
            root = Farm.unpack(archive, unpacked, manifest['entry'])
            row('archive', True, 'Unpacked with path, link, special-file and size guards')
            scan = scan_tree(unpacked, manifest['permissions'])
            row('imports', True, ', '.join(scan['imports']) or 'No Python imports')
            row('static scan', scan['ok'], json.dumps(scan['findings']) if scan['findings'] else 'No flagged code or secret patterns')
            row('microphone', True, scan['microphone'] + '; microphone access is not detected by this static scan')
            if manifest.get('selfcheck') and scan['ok']:
                ok = run_selfcheck(manifest, root)
                row('selfcheck', ok, 'Offline python:3.11-slim; 120 s limit; requires exit 0; output withheld')
            else:
                rows.append({'check': f'{relative}: selfcheck', 'result': 'SKIP',
                             'detail': 'Not declared' if not manifest.get('selfcheck') else 'Blocked by static scan failure'})
    except Exception as exc:
        # Exceptions/URLs and app output can contain credentials; never include them.
        row('submission', False, type(exc).__name__ + '; validation/download/extraction/check failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    try:
        paths = changed_manifests(args.repository, args.base, args.head)
        for path in paths:
            check_one(args.repository, path, rows)
        if not paths:
            rows.append({'check': 'selection', 'result': 'PASS', 'detail': 'No added or changed manifests (deletions need no archive check)'})
    except Exception as exc:
        rows.append({'check': 'selection', 'result': 'FAIL', 'detail': type(exc).__name__})
    args.report.write_text(json.dumps({'rows': rows}, indent=2) + '\n')
    for row in rows:
        print(json.dumps(row))
    return int(any(row['result'] == 'FAIL' for row in rows))


if __name__ == '__main__':
    sys.exit(main())
