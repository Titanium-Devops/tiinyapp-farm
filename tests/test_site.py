"""Static site contract checks. No browser, GUI, or deployment CLI is used."""

import copy
from datetime import date, timedelta
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET
from PIL import Image

from farm.farm import CatalogLinks, Farm
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SITE = runpy.run_path(str(ROOT / 'scripts/build-site.py'))
TODAY = date(2026, 9, 12)


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.references = []
        self.ids = set()
        self.tags = []
        self.text = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        for attribute in ('href', 'src'):
            if attribute in attrs:
                self.references.append(attrs[attribute])

    def handle_data(self, text):
        self.text.append(text)


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name) / 'dist'
        cls.count = SITE['build'](output=cls.output, today=TODAY)
        cls.apps = [json.loads(p.read_text()) for p in sorted((ROOT / 'manifests').glob('*.json'))]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_every_manifest_has_a_plot_and_complete_page(self):
        index = (self.output / 'index.html').read_text()
        self.assertEqual(index.count('<article class="plot">'), len(self.apps))
        for app in self.apps:
            with self.subTest(app=app['id']):
                doc = Document((self.output / 'apps' / app['id'] / 'index.html').read_text())
                visible = ' '.join(doc.text)
                for key in ('name', 'pitch', 'description', 'id', 'version', 'license', 'addedAt', 'updatedAt'):
                    self.assertIn(str(app[key]), visible)
                for url in (app['homepage'], app['repo'], app['author']['url'], app['release']['url']):
                    self.assertIn(url, doc.references)
                self.assertIn(app['release']['sha256'], visible)
                self.assertIn(str(app['release']['size']), visible)
                self.assertIn('farm install ' + app['id'], visible)
                if app['entry'] is None:
                    self.assertNotIn('farm start ' + app['id'], visible)
                    self.assertIn('no app to start', visible)
                else:
                    self.assertIn('farm start ' + app['id'], visible)
                for permission in app['permissions']:
                    self.assertIn(SITE['PERMISSIONS'][permission], visible)
                for model in app['requires']['device']['models']:
                    self.assertIn(model, visible)
                for port in app['requires']['ports']:
                    self.assertIn(str(port), visible)
                self.assertIn(str(app['requires']['device']['npuUnits']), visible)
                if 'health' in app:
                    self.assertIn(app['health'], visible)
                self.assertIn('Not verified by the farmhands.', visible)

    def test_sprouting_seed_keeps_story_and_social_without_install_or_release(self):
        app = copy.deepcopy(self.apps[0])
        del app['release']
        page = SITE['app_page'](app, TODAY)
        plot = SITE['plot'](app, TODAY)
        for html in (page, plot):
            self.assertIn('>Sprouting<', html)
            self.assertIn(app['pitch'], ' '.join(Document(html).text))
            self.assertNotIn('farm install', html)
        self.assertIn('No release yet. Follow the maker for the first planting.', page)
        self.assertNotIn('<h2>Release</h2>', page)
        self.assertNotIn('SHA-256', page)
        self.assertIn('seed-comments', page)
        self.assertIn(app['author']['url'], Document(page).references)
        owner_link = next(attrs for tag, attrs in Document(page).tags if 'data-seed-update' in attrs)
        self.assertIn('hidden', owner_link)
        self.assertEqual(owner_link['href'], '/seeds/?update=' + app['id'])

    def test_update_prefill_and_put_preserve_python_entry_images_and_screenshots(self):
        script = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  value = ''; files = []; hidden = false; disabled = false; checked = false;
  listeners = {}; options = [{ value: 'network' }, { value: 'files' }];
  classList = { toggle() {} };
  addEventListener(name, fn) { this.listeners[name] = fn; }
  append() {} setAttribute() {} focus() {}
  get selectedOptions() { return this.options.filter(option => option.selected); }
  querySelector() { return new Element(); }
}
const controls = new Map();
const control = id => { if (!controls.has(id)) controls.set(id, new Element()); return controls.get(id); };
control('seed-form').elements = { namedItem: control };
const seed = { id: 'test-seed', name: 'My seed', pitch: 'Pitch', description: 'Story', version: '1.0.0',
  license: 'MIT', homepage: 'https://example.org', entry: { python: 'my.module', args: ['a b', 'x'] },
  requires: { python: '3.11', ports: [8080], device: { models: ['test'], npuUnits: 1 } },
  tags: ['test'], permissions: ['network'], media: { icon: '/media/u/icon.png', gallery: ['/media/u/pic.png'] },
  screenshots: ['https://example.org/shot.png'] };
class Data extends Map { constructor() { super(); for (const [id, el] of controls) this.set(id, el.value); } }
let submitted, redirected;
const context = {
  URLSearchParams, FormData: Data, console,
  document: { getElementById: control, querySelectorAll: () => [], createElement: () => new Element() },
  window: { location: { search: '?update=test-seed', assign: url => { redirected = url; } } },
  refreshSession: async () => ({ email: 'maker@example.org', tiinyverse: { name: 'Maker', profileUrl: 'https://example.org/maker' } }),
  fetch: async (path, options) => {
    let result;
    if (path === '/api/seeds/mine') result = { seeds: [{ id: seed.id, canUpdate: true }] };
    else if (path === '/manifests/test-seed.json') result = seed;
    else { submitted = { path, ...options }; result = { statusUrl: '/farm/' }; }
    return { ok: true, json: async () => result };
  },
};
vm.runInNewContext(fs.readFileSync('site/assets/seeds.js', 'utf8').replace(/^import[^\n]+\n/, ''), context);
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(control('id').value, 'test-seed');
  assert.equal(control('id').readOnly, true);
  assert.equal(control('release-heading').textContent, 'Add your first release');
  assert.equal(control('ports').value, '8080');
  assert.equal(control('releaseUrl').value, '');
  control('seed-form').listeners.submit({ preventDefault() {}, currentTarget: control('seed-form') });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(submitted.path, '/api/seeds/test-seed');
  assert.equal(submitted.method, 'PUT');
  assert.deepEqual(JSON.parse(submitted.body.get('entry')), seed.entry);
  assert.equal(submitted.body.has('command'), false);
  assert.deepEqual(JSON.parse(submitted.body.get('media')), seed.media);
  assert.deepEqual(JSON.parse(submitted.body.get('screenshots')), seed.screenshots);
  assert.equal(redirected, '/farm/');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_seed_update_link_only_shows_for_verified_published_owner(self):
        script = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('site/assets/session.js', 'utf8').replace('export function', 'function');
(async () => {
  for (const [user, seeds, visible] of [
    [null, [], false], [{}, [{ id: 'seed', canUpdate: true }], false],
    [{ tiinyverse: {} }, [{ id: 'seed', canUpdate: false }], false],
    [{ tiinyverse: {} }, [{ id: 'other', canUpdate: true }], false],
    [{ tiinyverse: {} }, [{ id: 'seed', canUpdate: true }], true],
  ]) {
    const link = { hidden: true, dataset: { seedUpdate: 'seed' } };
    vm.runInNewContext(source, {
      document: { querySelectorAll: () => [], querySelector: () => link },
      fetch: async path => ({ ok: true, json: async () => path === '/api/me' ? { user } : { seeds } }),
    });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(link.hidden, !visible);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_required_pages_and_byte_identical_manifests(self):
        for path in ('index.html', 'plant/index.html', 'seeds/index.html', 'seeds/mine/index.html', 'farm/index.html', 'catalog.json', 'manifests/index.html', 'sitemap.xml', 'robots.txt', '404.html'):
            self.assertTrue((self.output / path).is_file(), path)
        for path in (ROOT / 'manifests').glob('*.json'):
            self.assertEqual(path.read_bytes(), (self.output / 'manifests' / path.name).read_bytes())

    def test_every_internal_link_and_fragment_resolves(self):
        for path in self.output.rglob('*.html'):
            source_url = 'https://tiinyapp.farm/' + path.relative_to(self.output).as_posix()
            for reference in Document(path.read_text()).references:
                parsed = urlsplit(urljoin(source_url, reference))
                if parsed.netloc != 'tiinyapp.farm':
                    continue
                if parsed.path == '/api/auth/github':
                    continue  # Worker OAuth route, not a static file.
                target = self.output / unquote(parsed.path).lstrip('/')
                if target.is_dir():
                    target /= 'index.html'
                with self.subTest(page=path.name, reference=reference):
                    self.assertTrue(target.is_file(), str(target))
                    if parsed.fragment:
                        self.assertIn(unquote(parsed.fragment), Document(target.read_text()).ids)

    def test_assets_marks_fonts_and_javascript_only_on_interactive_seed_pages(self):
        for path in self.output.rglob('*.html'):
            text = path.read_text()
            doc = Document(text)
            self.assertNotIn(chr(0x2014), text)
            self.assertNotIn('tiny' + 'app', text.lower())
            self.assertNotIn('data:image', text)
            scripts = [attrs for tag, attrs in doc.tags if tag == 'script']
            expected = []
            if path.relative_to(self.output).as_posix() == 'seeds/index.html':
                expected.append({'type': 'module', 'src': '/assets/seeds.js'})
            elif path.relative_to(self.output).as_posix().startswith('apps/'):
                expected.append({'type': 'module', 'src': '/assets/share.js'})
                expected.append({'type': 'module', 'src': '/assets/seed-media.js'})
                expected.append({'type': 'module', 'src': '/assets/social.js'})
            elif path.relative_to(self.output).as_posix() == 'farm/index.html':
                expected.append({'type': 'module', 'src': '/assets/farm.js'})
            expected.append({'type': 'module', 'src': '/assets/session.js'})
            self.assertEqual(scripts, expected)
            self.assertIn('data-farm-nav', text)
            for reference in ('/brand/tiiny-logo.svg', '/brand/titanium-bot-logo.svg', 'https://titanium.bot', 'https://tiiny.ai'):
                self.assertIn(reference, doc.references)
            self.assertIn('Brought to you by Titanium Bot', text)
            self.assertIn('Built for', text)
            self.assertIn('/assets/site.css', text)
        self.assertIn('/assets/hero.jpg', Document((self.output / 'index.html').read_text()).references)
        self.assertEqual((ROOT / 'site/assets/hero.jpg').read_bytes(), (self.output / 'assets/hero.jpg').read_bytes())
        self.assertTrue((self.output / 'assets/hero.jpg').read_bytes().startswith(b'\xff\xd8'))
        for path in (ROOT / 'brand').glob('*.svg'):
            self.assertEqual(path.read_bytes(), (self.output / 'brand' / path.name).read_bytes())

    def test_share_identity_and_cards(self):
        for path in self.output.rglob('*.html'):
            doc = Document(path.read_text())
            meta = {a.get('property', a.get('name')): a.get('content') for t, a in doc.tags if t == 'meta'}
            for key in ('og:title', 'og:description', 'og:image', 'og:url'):
                self.assertTrue(meta[key])
            self.assertEqual(meta['twitter:card'], 'summary_large_image')
            self.assertEqual(meta['theme-color'], '#090D14')
            for file in ('favicon.ico', 'favicon-32.png', 'favicon-192.png', 'apple-touch-icon.png'):
                self.assertIn('/brand/' + file, doc.references)
            self.assertIn('/site.webmanifest', doc.references)
            self.assertIn('/brand/icon-512.png', doc.references)
        for app in self.apps:
            with Image.open(self.output / 'apps' / app['id'] / 'card.png') as card:
                self.assertEqual(card.size, (1200, 630))
                self.assertEqual(card.format, 'PNG')
                self.assertGreater(len(card.getcolors(1200 * 630)), 100)
            doc = Document((self.output / 'apps' / app['id'] / 'index.html').read_text())
            meta = {a.get('property'): a.get('content') for t, a in doc.tags if t == 'meta'}
            self.assertEqual(meta['og:image'], 'https://tiinyapp.farm/apps/' + app['id'] + '/card.png')
            self.assertEqual(meta['og:description'], app['pitch'])
            self.assertEqual((meta['og:image:width'], meta['og:image:height']), ('1200', '630'))
            self.assertTrue(any(t == 'button' and 'data-share' in a for t, a in doc.tags))
        for file in (ROOT / 'brand').iterdir():
            if file.is_file():
                self.assertEqual(file.read_bytes(), (self.output / 'brand' / file.name).read_bytes())
        manifest = json.loads((self.output / 'site.webmanifest').read_text())
        self.assertEqual(manifest['name'], 'tiinyapp.farm')
        self.assertEqual(manifest['theme_color'], '#090D14')
        self.assertEqual({i['sizes'] for i in manifest['icons']}, {'192x192', '512x512'})

    def test_build_known_maker_card(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            for directory in ('manifests', 'brand', 'docs', 'site/assets', 'site/fonts'):
                shutil.copytree(ROOT / directory, source / directory)
            (source / 'site/makers.json').write_text(json.dumps([{
                'handle': 'test-maker', 'name': 'Test Maker', 'bio': 'Growing little apps.',
                'avatar': '/brand/icon-512.png', 'tiinyverse': 'https://www.tiinyverse.com/users/test'
            }]))
            SITE['build'](source=source, today=TODAY)
            with Image.open(source / 'site/dist/makers/test-maker/card.png') as card:
                self.assertEqual(card.size, (1200, 630))

    def test_badges_are_independent_and_use_utc_date_boundaries(self):
        app = copy.deepcopy(self.apps[0])
        app['verified'] = True
        app['entry'] = None
        for age, expected in ((-1, False), (0, True), (29, True), (30, False), (31, False)):
            app['addedAt'] = (TODAY - timedelta(days=age)).isoformat()
            html = SITE['badges'](app, TODAY)
            self.assertEqual('>New<' in html, expected)
            self.assertIn('>Verified<', html)
            self.assertIn('>Library<', html)
        app['verified'] = False
        app['entry'] = {'command': 'run'}
        html = SITE['badges'](app, TODAY)
        self.assertNotIn('>Verified<', html)
        self.assertNotIn('>Library<', html)

    def test_catalog_build_with_future_seed_and_rebuild(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            for directory in ('manifests', 'brand', 'docs'):
                shutil.copytree(ROOT / directory, source / directory)
            shutil.copytree(ROOT / 'site/assets', source / 'site/assets')
            shutil.copytree(ROOT / 'site/fonts', source / 'site/fonts')
            fourth = copy.deepcopy(self.apps[0])
            fourth.update(id='fourth-seed', name='Fourth <seed> & friends', entry={'command': 'python run.py --label "A&B"'}, tags=['test'], screenshots=['https://example.org/screenshot.jpg'])
            path = source / 'manifests/fourth-seed.json'
            path.write_text(json.dumps(fourth, indent=4) + '\n')
            self.assertEqual(SITE['build'](source=source, today=TODAY), len(self.apps) + 1)
            dest = source / 'site/dist'
            self.assertEqual(len(list((dest / 'apps').glob('*/index.html'))), len(self.apps) + 1)
            self.assertEqual((dest / 'manifests/fourth-seed.json').read_bytes(), path.read_bytes())
            text = (dest / 'apps/fourth-seed/index.html').read_text()
            self.assertIn('Fourth &lt;seed&gt; &amp; friends', text)
            self.assertIn('https://example.org/screenshot.jpg', Document(text).references)
            self.assertIn(fourth['entry']['command'], ' '.join(Document(text).text))
            path.unlink()
            SITE['build'](source=source, today=TODAY)
            self.assertFalse((dest / 'apps/fourth-seed').exists())
            self.assertFalse((dest / 'manifests/fourth-seed.json').exists())

    def test_catalog_is_readable_by_the_existing_installer(self):
        import io
        raw = (self.output / 'manifests/index.html').read_bytes()
        parser = CatalogLinks()
        parser.feed(raw.decode())
        self.assertEqual(sorted(parser.ids), sorted(a['id'] for a in self.apps))
        with patch('farm.farm.urlopen', return_value=io.BytesIO(raw)):
            farm = Farm(home=Path(self.temp.name) / 'home')
            self.assertEqual(farm.catalog_ids(), sorted(a['id'] for a in self.apps))

    def test_sitemap_and_field_documentation(self):
        tree = ET.parse(self.output / 'sitemap.xml')
        urls = {element.text for element in tree.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')}
        expected = {'https://tiinyapp.farm' + path for path in ('/', '/plant/', '/seeds/', '/manifests/')}
        expected.update('https://tiinyapp.farm/apps/' + app['id'] + '/' for app in self.apps)
        self.assertEqual(urls, expected)
        self.assertIn('Sitemap: https://tiinyapp.farm/sitemap.xml', (self.output / 'robots.txt').read_text())
        schema = json.loads((ROOT / 'docs/manifest.schema.json').read_text())
        self.assertEqual(set(SITE['FIELDS']), set(schema['properties']))

    def test_mockup_tokens_and_phone_layout_constraints(self):
        css = (self.output / 'assets/site.css').read_text()
        mockup = (ROOT / 'site/design/mockup-approved.html').read_text()
        tokens = dict(re.findall(r'(--[a-z]+):(#[A-Fa-f0-9]{6})', mockup))
        actual = dict(re.findall(r'(--[a-z]+):(#[A-Fa-f0-9]{6})', css))
        self.assertEqual(actual, tokens)
        self.assertIn('min-height:44px;min-width:44px', css)
        self.assertIn('white-space:pre-wrap', css)
        self.assertIn('overflow-wrap:anywhere', css)
        self.assertIn('minmax(min(250px,100%),1fr)', css)
        self.assertIn('minmax(min(220px,100%),1fr)', css)
        # 390px viewport minus wrap padding = 342; a plot has 304px inside.
        self.assertEqual(390 - 2 * 24, 342)
        self.assertEqual(342 - 2 * (18 + 1), 304)
        self.assertIn('@media(min-width:701px)', css)

    def test_deploy_configuration(self):
        config = tomllib.loads((ROOT / 'wrangler.toml').read_text())
        self.assertEqual(config['name'], 'tiinyapp-farm')
        self.assertEqual(config['main'], 'worker/main.mjs')
        self.assertEqual(config['assets']['binding'], 'ASSETS')
        self.assertTrue(set(['/api/*', '/seeds-files/*', '/farm/*', '/makers/*', '/media/*', '/seeds/mine/*']).issubset(config['assets']['run_worker_first']))
        self.assertEqual(config['kv_namespaces'][0]['binding'], 'FARM')
        self.assertEqual(config['r2_buckets'][0], {'binding': 'SEEDS', 'bucket_name': 'farm-seeds'})
        self.assertEqual(config['durable_objects']['bindings'][0]['class_name'], 'FarmCoordinator')
        self.assertEqual(config['routes'], [{'pattern': 'tiinyapp.farm', 'custom_domain': True}])
        self.assertEqual(config['assets']['directory'], './site/dist')
        self.assertEqual(config['assets']['not_found_handling'], '404-page')
        self.assertEqual(config['assets']['html_handling'], 'force-trailing-slash')
        workflow = (ROOT / '.github/workflows/site.yml').read_text()
        for required in ('branches: [main]', 'python3 scripts/build-site.py', 'python3 -m unittest', 'command: deploy', 'secrets.CLOUDFLARE_API_TOKEN', 'secrets.CLOUDFLARE_ACCOUNT_ID'):
            self.assertIn(required, workflow)

    def test_seed_cards_read_signed_out_and_lock_proof_and_planting(self):
        doc = Document((self.output / 'seeds/index.html').read_text())
        visible = ' '.join(doc.text)
        for phrase in ('Your farm account', 'Prove your Tiiny', 'Plant a seed',
                       'Do I need GitHub?', 'No. Use your email', 'paste this code anywhere in the bio'):
            self.assertIn(phrase, visible)
        cards = [attrs for tag, attrs in doc.tags if attrs.get('class') == 'seed-card']
        self.assertEqual(len(cards), 3)
        locked = [attrs['id'] for tag, attrs in doc.tags if tag == 'fieldset' and 'disabled' in attrs]
        self.assertEqual(locked, ['proof-fields', 'seed-fields'])
        labels = {attrs['for'] for tag, attrs in doc.tags if tag == 'label' and 'for' in attrs}
        for tag, attrs in doc.tags:
            if tag in ('input', 'textarea', 'select') and attrs.get('type') != 'checkbox':
                self.assertIn(attrs['id'], labels)
        css = (self.output / 'assets/site.css').read_text()
        self.assertNotIn('grid-template-columns:repeat(3,minmax(0,1fr))', css)
        self.assertIn('.seed-form-grid{display:grid;grid-template-columns:minmax(0,1fr)', css)
        self.assertIn('@media(min-width:900px){.seed-form-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}', css)
        self.assertIn('.seed-wide{grid-column:1/-1}', css)
        html = (self.output / 'seeds/index.html').read_text()
        for field in ('description', 'archive', 'permissions'):
            self.assertIn(f'<div class="seed-field seed-wide"><label for="{field}">', html)
        self.assertIn('<details class="seed-wide">', html)

    def test_social_strip_has_accessible_controls_and_auth_invitation(self):
        for app in self.apps:
            doc = Document((self.output / 'apps' / app['id'] / 'index.html').read_text())
            self.assertTrue({'social-heading', 'social-status', 'seed-thumb', 'thumb-count',
                             'social-signin', 'seed-comments', 'comment-form', 'comment-text'}.issubset(doc.ids))
            controls = {attrs.get('id'): attrs for tag, attrs in doc.tags if attrs.get('id')}
            self.assertEqual(controls['seed-thumb']['aria-pressed'], 'false')
            self.assertIn('disabled', controls['seed-thumb'])
            self.assertIn('hidden', controls['comment-form'])
            self.assertEqual(controls['comment-text']['maxlength'], '1000')
            self.assertEqual(controls['social-status']['aria-live'], 'polite')
            self.assertIn('/seeds/', doc.references)
            self.assertTrue(any(attrs.get('data-seed-social') == app['id'] for tag, attrs in doc.tags))

    def test_comment_rendering_keeps_untrusted_text_in_text_nodes(self):
        script = r'''import assert from 'node:assert/strict';
class Element {
  children = [];
  listeners = {};
  constructor(tag) { this.tag = tag; }
  set innerHTML(value) { throw new Error('HTML insertion is forbidden'); }
  append(...children) { this.children.push(...children); }
  addEventListener(name, fn) { this.listeners[name] = fn; }
}
globalThis.document = { createElement: tag => new Element(tag), querySelector: () => null, querySelectorAll: () => [] };
globalThis.fetch = async () => ({ ok: true, json: async () => ({ user: null }) });
const { commentCard } = await import(process.argv[1]);
const text = '<img src=x onerror=alert(1)> & welcome';
let removed;
const card = commentCard({ id: 'c1', text, at: 1726140000000, canDelete: true,
  author: { handle: 'a/b', name: '<script>bad()</script>', avatar: '/media/maker/avatar.png' } }, id => { removed = id; });
assert.equal(card.children[1].textContent, text);
assert.equal(card.children[0].children[1].textContent, '<script>bad()</script>');
assert.equal(card.children[0].children[1].href, '/makers/a%2Fb/');
assert.equal(card.children[0].children[0].src, '/media/maker/avatar.png');
card.children[2].listeners.click();
assert.equal(removed, 'c1');
const anonymous = commentCard({ text: 'hello', at: 'invalid', author: { avatar: 'javascript:evil()' }, canDelete: false }, () => {});
assert.equal(anonymous.children.length, 2);
assert.equal(anonymous.children[0].children.length, 1);
assert.equal(anonymous.children[0].children[0].tag, 'span');
'''
        result = subprocess.run(['node', '--input-type=module', '-e', script,
                                 (ROOT / 'site/assets/social.js').as_uri()], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_seed_faces_and_legacy_links(self):
        app = copy.deepcopy(self.apps[0])
        app['media'] = {'icon': 'https://example.org/icon.png', 'header': 'https://example.org/header.webp',
                        'gallery': ['https://example.org/gallery.jpg']}
        app['links'] = {'repo': 'https://example.org/source', 'homepage': 'https://example.org/home',
                        'video': 'https://youtu.be/dQw4w9WgXcQ'}
        doc = Document(SITE['app_page'](app, TODAY))
        for url in (*app['media'].values(),):
            if isinstance(url, str):
                self.assertIn(url, doc.references)
        self.assertIn(app['media']['gallery'][0], doc.references)
        self.assertIn(app['links']['repo'], doc.references)
        self.assertIn(app['links']['homepage'], doc.references)
        self.assertTrue(any(tag == 'dialog' for tag, attrs in doc.tags))
        self.assertFalse(any(tag == 'iframe' for tag, attrs in doc.tags))
        self.assertTrue(any(attrs.get('data-youtube-id') == 'dQw4w9WgXcQ' for tag, attrs in doc.tags))
        self.assertFalse(any('youtube-nocookie' in url for url in doc.references))
        self.assertIn(app['media']['icon'], Document(SITE['plot'](app, TODAY)).references)
        app['links']['video'] = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        self.assertIn('data-youtube-id="dQw4w9WgXcQ"', SITE['app_page'](app, TODAY))
        app.pop('links')
        legacy = Document(SITE['app_page'](app, TODAY))
        self.assertIn(app['homepage'], legacy.references)
        self.assertIn(app['repo'], legacy.references)
        form = Document((self.output / 'seeds/index.html').read_text())
        self.assertTrue({'seed-icon', 'seed-header', 'seed-gallery', 'repo', 'video'}.issubset(form.ids))
        gallery = next(attrs for tag, attrs in form.tags if attrs.get('id') == 'seed-gallery')
        self.assertIn('multiple', gallery)

    def test_private_farm_shell_and_catalog(self):
        html = (self.output / 'farm/index.html').read_text()
        doc = Document(html)
        self.assertTrue({'maker-name', 'maker-avatar', 'maker-bio', 'maker-links', 'maker-form',
                         'bio', 'avatar', 'github', 'website', 'youtube', 'my-seeds', 'refresh-seeds'}.issubset(doc.ids))
        inputs = {attrs['id']: attrs for tag, attrs in doc.tags if tag in ('input', 'textarea')}
        self.assertEqual(inputs['bio']['maxlength'], '600')
        self.assertEqual(inputs['avatar']['accept'], 'image/png,image/jpeg,image/webp')
        legacy = Document((self.output / 'seeds/mine/index.html').read_text())
        self.assertIn({'http-equiv': 'refresh', 'content': '0;url=/farm/'}, [attrs for tag, attrs in legacy.tags if tag == 'meta'])
        self.assertEqual(json.loads((self.output / 'catalog.json').read_text()), self.apps)
        self.assertIn('id="account-farm" href="/farm/" hidden', (self.output / 'seeds/index.html').read_text())

    def test_seed_tabs_control_three_panels_with_only_first_visible(self):
        doc = Document((self.output / 'seeds/index.html').read_text())
        tablists = [attrs for tag, attrs in doc.tags if attrs.get('role') == 'tablist']
        tabs = [(tag, attrs) for tag, attrs in doc.tags if attrs.get('role') == 'tab']
        panels = [attrs for tag, attrs in doc.tags if attrs.get('role') == 'tabpanel']
        self.assertEqual(len(tablists), 1)
        self.assertEqual(len(tabs), 3)
        self.assertEqual(len(panels), 3)
        for index, ((tag, tab), panel) in enumerate(zip(tabs, panels)):
            self.assertEqual(tag, 'button')
            self.assertEqual(tab['type'], 'button')
            self.assertEqual(tab['aria-controls'], panel['id'])
            self.assertEqual(panel['aria-labelledby'], tab['id'])
            self.assertEqual(tab['aria-selected'], 'true' if index == 0 else 'false')
            self.assertEqual(tab['tabindex'], '0' if index == 0 else '-1')
            self.assertEqual('hidden' in panel, index != 0)
            self.assertNotIn('disabled', tab)
        for label in ('01 Your farm account', '02 Prove your Tiiny', '03 Plant a seed'):
            self.assertIn(label, doc.text)

    def test_cli_works_outside_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/build-site.py'), '--output', str(Path(temp) / 'dist'), '--today', TODAY.isoformat()], cwd=temp, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f'Built {len(self.apps)} app pages', result.stdout)


if __name__ == '__main__':
    unittest.main()
