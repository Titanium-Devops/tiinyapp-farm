"""The OpenAPI document against the Worker's own route table.

The Worker decides routes by comparing the request path against a string, an array of strings,
a prefix or a regular expression. This walks worker/*.mjs for those comparisons and checks them
both ways: every route the Worker answers is a path in the document, and every path in the
document that is not a static file is a route the Worker answers.

A comparison is read only when it is made against the URL path itself and is rooted at /, which
is what a route looks like. The one pattern in the tree that is tested against a path variable
and is not rooted is the archive filename check inside the /seeds-files/ branch of main.mjs, and
a filename is not a route.
"""

import json
from pathlib import Path
import re
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = runpy.run_path(str(ROOT / 'worker/openapi.py'))['spec']()
TARGETS = ('path', 'pathname', 'url.pathname')
METHODS = ('get', 'put', 'post', 'delete', 'patch', 'head', 'options')


def read_regex(text, start):
    """One JavaScript /regex/ literal beginning at start, as (source, end), or None.

    Escapes and character classes both hide a slash that does not end the literal."""
    if start >= len(text) or text[start] != '/':
        return None
    index, inside = start + 1, False
    while index < len(text):
        character = text[index]
        if character == '\\':
            index += 2
            continue
        if character == '\n':
            return None
        if inside:
            inside = character != ']'
        elif character == '[':
            inside = True
        elif character == '/':
            end = index + 1
            while end < len(text) and text[end] in 'dgimsuvy':
                end += 1
            return text[start + 1:index], end
        index += 1
    return None


def comparisons(text):
    """Every comparison this module makes against a URL path, as (kind, value)."""
    found = []
    for match in re.finditer(r"([\w.]+)\s*===\s*'([^']*)'", text):
        if match.group(1) in TARGETS:
            found.append(('is', match.group(2)))
    for match in re.finditer(r"\[([^\]]*)\]\.includes\(([\w.]+)\)", text):
        if match.group(2) in TARGETS:
            found.extend(('is', value) for value in re.findall(r"'([^']*)'", match.group(1)))
    for match in re.finditer(r"([\w.]+)\.startsWith\('([^']*)'\)", text):
        if match.group(1) in TARGETS:
            found.append(('under', match.group(2)))
    for match in re.finditer(r"([\w.]+)\.match\(", text):
        literal = read_regex(text, match.end())
        if literal and match.group(1) in TARGETS:
            found.append(('matches', literal[0]))
    for match in re.finditer(r"\.test\(([\w.]+)\)", text):
        if match.group(1) not in TARGETS:
            continue
        line = text.rfind('\n', 0, match.start()) + 1
        for start in range(line, match.start()):
            literal = read_regex(text, start)
            if literal and literal[1] == match.start():
                found.append(('matches', literal[0]))
                break
    # A route is rooted at the site root; anything else is a check on part of a path.
    return [(kind, value) for kind, value in found
            if value.startswith('/') or value.startswith('^\\/') or value.startswith('^\\/'.replace('\\', ''))]


def routes():
    """Every path comparison in the Worker, as {(kind, value): {modules}}."""
    table = {}
    for source in sorted((ROOT / 'worker').glob('*.mjs')):
        for comparison in comparisons(source.read_text(encoding='utf-8')):
            table.setdefault(comparison, set()).add(source.name)
    return table


def samples(path):
    """The concrete paths a route comparison could be tried on, index page and all.

    Every path parameter in the document carries the example this fills it with, so a reader and
    this walk are looking at the same URL."""
    examples = {parameter['name']: parameter['example']
                for method, operation in SPEC['paths'][path].items() if method != 'x-farm-source'
                for parameter in operation.get('parameters', []) if parameter['in'] == 'path'}
    filled = re.sub(r'\{(\w+)\}', lambda found: examples[found.group(1)], path)
    variants = {filled, filled.rstrip('/') or '/'}
    if filled.endswith('/'):
        variants.add(filled + 'index.html')
    return variants


def answers(comparison, path):
    """Whether one comparison in the Worker would send this path to its route."""
    kind, value = comparison
    for sample in samples(path):
        if kind == 'is' and value == sample:
            return True
        if kind == 'under' and sample.startswith(value):
            return True
        if kind == 'matches' and re.search(value.replace('(?<![a-zA-Z0-9_-])', ''), sample):
            return True
    return False


class OpenAPITests(unittest.TestCase):
    def test_the_document_is_json_and_says_what_it_is(self):
        rendered = json.dumps(SPEC, indent=2)
        self.assertEqual(json.loads(rendered)['openapi'], '3.1.0')
        self.assertEqual(SPEC['servers'], [{'url': 'https://tiinyapp.farm'}])
        self.assertEqual(SPEC['info']['version'],
                         re.search(r'^version\s*=\s*"([^"]+)"',
                                   (ROOT / 'pyproject.toml').read_text(), re.M).group(1))
        self.assertNotIn(chr(0x2014), rendered)

    def test_every_operation_is_described_and_answers_something(self):
        schemes = set(SPEC['components']['securitySchemes'])
        tags = {tag['name'] for tag in SPEC['tags']}
        for path, item in SPEC['paths'].items():
            self.assertIn('x-farm-source', item, path)
            self.assertTrue(set(item) - {'x-farm-source'}, path)
            for method, operation in item.items():
                if method == 'x-farm-source':
                    continue
                with self.subTest(route=method.upper() + ' ' + path):
                    self.assertIn(method, METHODS)
                    self.assertTrue(operation['summary'])
                    self.assertTrue(operation['description'])
                    self.assertTrue(operation['responses'])
                    self.assertLessEqual({tag for tag in operation.get('tags', [])}, tags)
                    for requirement in operation['security']:
                        self.assertLessEqual(set(requirement), schemes)
                    named = set(re.findall(r'\{(\w+)\}', path))
                    self.assertEqual({p['name'] for p in operation.get('parameters', [])
                                      if p['in'] == 'path'}, named)
                    for answer in operation['responses'].values():
                        self.assertTrue(answer['description'])

    def test_every_reference_in_the_document_resolves(self):
        schemas = SPEC['components']['schemas']
        for reference in re.findall(r'"\$ref": "([^"]+)"', json.dumps(SPEC)):
            self.assertTrue(reference.startswith('#/components/schemas/'), reference)
            self.assertIn(reference.rsplit('/', 1)[1], schemas)

    def test_every_route_the_worker_answers_is_in_the_document(self):
        for comparison, modules in routes().items():
            with self.subTest(comparison=comparison, modules=sorted(modules)):
                self.assertTrue(any(answers(comparison, path) for path in SPEC['paths']),
                                'no path in the document is sent here')

    def test_every_documented_path_is_a_route_or_a_static_file(self):
        table = routes()
        for path, item in SPEC['paths'].items():
            source = item['x-farm-source']
            with self.subTest(path=path, source=source):
                reached = {module for comparison, modules in table.items()
                           if answers(comparison, path) for module in modules}
                if source == 'assets':
                    self.assertFalse(reached & {'index.mjs', 'seeds.mjs'},
                                     'a static file the Worker would answer instead')
                    continue
                self.assertTrue(reached, 'no comparison in the Worker sends anything here')
                self.assertIn(source, reached, 'not compared in the module it is filed under')

    def test_the_walk_reads_the_shapes_the_worker_actually_uses(self):
        """The extraction is the test, so it is worth proving it found each kind of comparison."""
        table = routes()
        self.assertIn(('is', '/api/me'), table)
        self.assertIn(('is', '/api/media'), table)
        self.assertIn(('under', '/api/media/'), table)
        self.assertIn(('under', '/seeds-files/'), table)
        self.assertEqual(table[('is', '/api/me')], {'index.mjs'})
        self.assertTrue(any(kind == 'matches' and value.endswith(r'\/art$')
                            for kind, value in table))
        self.assertTrue(any(kind == 'matches' and 'release-check' in value
                            for kind, value in table))
        self.assertGreater(len(table), 25)

    def test_the_tokens_the_document_promises_are_the_ones_the_worker_takes(self):
        """Five routes accept a farm_ token. A sixth appearing here means the Worker changed."""
        worker = (ROOT / 'worker/index.mjs').read_text(encoding='utf-8')
        bearer = worker.split('const bearerRoute =')[1].split(';')[0]
        taking = {(method.lower(), path) for path, item in SPEC['paths'].items()
                  for method, operation in item.items() if method != 'x-farm-source'
                  and any('farmToken' in requirement for requirement in operation['security'])}
        self.assertEqual(taking, {('post', '/api/seeds'), ('put', '/api/seeds/{id}'),
                                  ('post', '/api/media'), ('get', '/api/seeds/mine'),
                                  ('get', '/api/seeds/{id}/art'), ('post', '/api/seeds/{id}/art')})
        for _, path in taking:
            self.assertIn(path.split('/{')[0], bearer)


if __name__ == '__main__':
    unittest.main()
