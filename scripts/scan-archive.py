#!/usr/bin/env python3
"""Conservative, stdlib-only source scan; findings are not a security guarantee."""
import argparse
import ast
import json
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from farm.farm import Farm  # noqa: E402

SECRET_PATTERNS = {
    'AWS access key': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'GitHub token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b',
    'OpenAI key': rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b',
    'Bearer token': rb'(?i)\bBearer[ \t]+[A-Za-z0-9_~+/.=-]{16,}',
    'private key': rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----',
}
NETWORK = ('socket', 'ssl', 'http', 'urllib.request', 'urllib3', 'requests',
           'httpx', 'aiohttp', 'websockets', 'ftplib', 'smtplib', 'asyncio')


def scan_tree(root, permissions):
    imports, findings = set(), []

    def flag(path, line, kind, detail):
        findings.append({'file': path.relative_to(root).as_posix(), 'line': line,
                         'kind': kind, 'detail': detail})

    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        # Scan bytes, including dotfiles and non-Python assets; never echo a match.
        with path.open('rb') as source:
            overlap = b''
            found = set()
            while chunk := source.read(65536):
                data = overlap + chunk
                for label, pattern in SECRET_PATTERNS.items():
                    if label not in found and re.search(pattern, data):
                        flag(path, 0, 'secret', label + ' pattern found (redacted)')
                        found.add(label)
                overlap = data[-8192:]
        if path.suffix != '.py':
            continue
        try:
            tree = ast.parse(path.read_bytes(), filename=str(path))
        except (SyntaxError, UnicodeError, ValueError):
            flag(path, 0, 'syntax', 'Python source could not be parsed')
            continue
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    imports.add(item.name)
                    aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                imports.add('.' * node.level + module)
                for item in node.names:
                    aliases[item.asname or item.name] = module + '.' + item.name
            else:
                continue
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module or '', *[(node.module or '') + '.' + item.name for item in node.names]]
            for name in names:
                if any(name == prefix or name.startswith(prefix + '.') for prefix in NETWORK) and 'network' not in permissions:
                    flag(path, node.lineno, 'permission', name + ' needs declared network permission')
                if name == 'subprocess' or name.startswith('subprocess.'):
                    flag(path, node.lineno, 'shell', 'subprocess needs shell permission; shell is forbidden')
                if name == 'ctypes' or name.startswith('ctypes.'):
                    flag(path, node.lineno, 'unsafe', 'ctypes native code access is forbidden')

        def name_of(node):
            if isinstance(node, ast.Name):
                return aliases.get(node.id, node.id)
            if isinstance(node, ast.Attribute):
                return name_of(node.value) + '.' + node.attr
            return ''

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = name_of(node.func)
            if name in ('eval', 'exec', 'builtins.eval', 'builtins.exec', '__import__', 'importlib.import_module'):
                flag(path, node.lineno, 'unsafe', name + ' dynamic execution/import is forbidden')
            if name in ('os.system', 'os.popen') or name.startswith(('os.exec', 'os.spawn', 'os.posix_spawn')):
                flag(path, node.lineno, 'shell', name + ' needs shell permission; shell is forbidden')
    return {'imports': sorted(imports), 'findings': findings,
            'microphone': 'declared' if 'microphone' in permissions else 'not declared',
            'ok': not findings}


def scan_archive(archive, manifest):
    with tempfile.TemporaryDirectory(prefix='farm-scan-') as temporary:
        root = Path(temporary)
        Farm.unpack(archive, root, manifest['entry'])
        return scan_tree(root, manifest['permissions'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    try:
        result = scan_archive(args.archive, json.loads(args.manifest.read_text()))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': type(exc).__name__}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
