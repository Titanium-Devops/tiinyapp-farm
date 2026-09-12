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

    def test_home_uses_featured_editorial_items_and_ledger_rows(self):
        index = (self.output / 'index.html').read_text()
        featured = [app for app in self.apps if app.get('featured')][:6]
        self.assertEqual(index.count('<article class="item">'), len(featured))
        self.assertEqual(index.count('data-catalog-search='), len(self.apps))
        self.assertIn('Picked by the maintainers', index)
        self.assertIn('Browse the catalog with filters', index)
        self.assertNotIn('<article class="plot">', index)
        for app in featured:
            featured_html = index.split('<section class="feat', 1)[1].split('</section>', 1)[0]
            self.assertIn(app['name'], featured_html)
        for app in self.apps:
            self.assertTrue(app.get('featured'))

    def test_every_manifest_has_a_complete_locked_app_page(self):
        for app in self.apps:
            with self.subTest(app=app['id']):
                doc = Document((self.output / 'apps' / app['id'] / 'index.html').read_text())
                visible = ' '.join(doc.text)
                for key in ('name', 'pitch', 'description', 'id', 'version', 'license'):
                    self.assertIn(str(app[key]), visible)
                for url in (app['homepage'], app['repo']):
                    self.assertIn(url, doc.references)
                self.assertIn(app['release']['sha256'][:12], visible)
                self.assertIn(f'{app["release"]["size"] / 1_000_000:.1f} MB', visible)
                self.assertIn('farm install ' + app['id'], visible)
                self.assertIn('farm start ' + app['id'], visible)
                for permission in app['permissions']:
                    self.assertIn({'microphone': 'Microphone', 'files': 'Files', 'network': 'Network', 'device': 'Your Tiiny'}[permission], visible)
                for model in app['requires']['device']['models']:
                    self.assertIn(model, visible)
                for port in app['requires']['ports']:
                    self.assertIn(str(port), visible)
                self.assertIn('Not reviewed yet', visible)
                self.assertIn('Grown by', visible)
                self.assertIn('class="rail"', (self.output / 'apps' / app['id'] / 'index.html').read_text())

    def test_sprouting_seed_keeps_story_and_social_without_install_or_release(self):
        app = copy.deepcopy(self.apps[0])
        del app['release']
        page = SITE['app_page'](app, TODAY)
        plot = SITE['plot'](app, TODAY)
        for html in (page, plot):
            self.assertIn('>No release yet<', html)
            self.assertIn(app['pitch'], ' '.join(Document(html).text))
            self.assertNotIn('farm install', html)
        self.assertIn('No release yet. This app cannot be installed.', page)
        self.assertIn('<h3>Release</h3><p>No release yet</p>', page)
        self.assertNotIn('SHA-256', page)
        self.assertIn('seed-comments', page)
        self.assertIn(app['author']['url'], Document(page).references)
        owner_link = next(attrs for tag, attrs in Document(page).tags if 'data-seed-update' in attrs)
        self.assertIn('hidden', owner_link)
        self.assertEqual(owner_link['href'], '/submit/?update=' + app['id'])

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
  attributes = {};
  append() {} focus() {}
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  get selectedOptions() { return this.options.filter(option => option.selected); }
  querySelector() { return new Element(); }
}
const controls = new Map();
const control = id => { if (!controls.has(id)) controls.set(id, new Element()); return controls.get(id); };
control('seed-form').elements = { namedItem: control };
const panels = ['account-panel', 'proof-panel', 'seed-panel'];
const tabs = panels.map(id => { const tab = new Element(); tab.setAttribute('aria-controls', id); return tab; });
const windowListeners = {};
const permissions = ['microphone', 'files', 'network', 'device'].map(value => Object.assign(new Element(), { value }));
const seed = { id: 'test-seed', name: 'My seed', pitch: 'Pitch', description: 'Story', version: '1.0.0',
  license: 'MIT', homepage: 'https://example.org', entry: { python: 'my.module', args: ['a b', 'x'] },
  requires: { python: '3.11', ports: [8080], device: { models: ['test'], npuUnits: 1 } },
  tags: ['test'], permissions: ['network'], media: { icon: '/media/u/icon.png', gallery: ['/media/u/pic.png'] },
  screenshots: ['https://example.org/shot.png'] };
class Data extends Map { constructor() { super(); for (const [id, el] of controls) this.set(id, el.value); } }
let submitted, redirected;
const context = {
  URLSearchParams, FormData: Data, console,
  document: { getElementById: control, querySelectorAll: selector => selector === '#permissions input[type=checkbox]' ? permissions : selector === '.seed-tabs [role=tab]' ? tabs : [], createElement: () => new Element() },
  window: { addEventListener: (event, fn) => { windowListeners[event] = fn; }, location: { hash: '#account-panel', search: '?update=test-seed', assign: url => { redirected = url; } } },
  refreshSession: async () => ({ email: 'maker@example.org', tiinyverse: { name: 'Maker', profileUrl: 'https://example.org/maker' } }),
  fetch: async (path, options) => {
    let result;
    if (path === '/api/seeds/mine') result = { seeds: [{ id: seed.id, canUpdate: true }] };
    else if (path === '/manifests/test-seed.json') result = seed;
    else { submitted = { path, ...options }; result = { statusUrl: '/account/' }; }
    return { ok: true, json: async () => result };
  },
};
vm.runInNewContext(fs.readFileSync('site/assets/seeds.js', 'utf8').replace(/^import[^\n]+\n/, ''), context);
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(control('account-panel').hidden, false);
  assert.equal(control('seed-panel').hidden, true);
  context.window.location.hash = '#seed-panel';
  windowListeners.hashchange();
  assert.equal(control('account-panel').hidden, true);
  assert.equal(control('seed-panel').hidden, false);
  assert.equal(control('id').value, 'test-seed');
  assert.equal(control('id').readOnly, true);
  assert.equal(control('release-heading').textContent, 'Add your first release');
  assert.equal(control('releaseChoice').value, 'no');
  assert.equal(control('release-fields').hidden, true);
  for (const id of ['version', 'releaseUrl', 'archive']) assert.equal(control(id).disabled, true);
  assert.equal(control('command').disabled, false);
  control('releaseChoice').value = 'yes';
  control('seed-form').listeners.change({ target: { name: 'releaseChoice' } });
  assert.equal(control('release-fields').hidden, false);
  for (const id of ['version', 'releaseUrl', 'archive']) assert.equal(control(id).disabled, false);
  control('releaseChoice').value = 'no';
  control('seed-form').listeners.change({ target: { name: 'releaseChoice' } });
  assert.equal(control('release-fields').hidden, true);
  assert.equal(control('releaseUrl').value, '');
  control('seed-form').listeners.submit({ preventDefault() {}, currentTarget: control('seed-form') });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(submitted.path, '/api/seeds/test-seed');
  assert.equal(submitted.method, 'PUT');
  assert.deepEqual(JSON.parse(submitted.body.get('entry')), seed.entry);
  assert.equal(submitted.body.get('python'), seed.requires.python);
  assert.equal(submitted.body.get('ports'), seed.requires.ports.join(','));
  assert.equal(submitted.body.get('models'), seed.requires.device.models.join(','));
  assert.equal(submitted.body.get('npuUnits'), String(seed.requires.device.npuUnits));
  assert.equal(submitted.body.get('tags'), seed.tags.join(','));
  assert.equal(submitted.body.get('permissions'), 'network');
  assert.equal(submitted.body.has('command'), false);
  assert.equal(submitted.body.has('releaseUrl'), false);
  assert.equal(submitted.body.has('archive'), false);
  assert.equal(submitted.body.get('version'), seed.version);
  assert.deepEqual(JSON.parse(submitted.body.get('media')), seed.media);
  assert.deepEqual(JSON.parse(submitted.body.get('screenshots')), seed.screenshots);
  assert.equal(redirected, '/account/');
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
        for path in ('index.html', 'catalog/index.html', 'install/index.html', 'submit/index.html', 'account/index.html', 'docs/agents/index.html', 'llms.txt', 'catalog.json', 'categories.json', 'manifests/index.html', 'sitemap.xml', 'robots.txt', '404.html'):
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
                if parsed.path == '/api/auth/github' or parsed.path.startswith(('/makers/', '/media/')):
                    continue  # Worker routes (OAuth, maker pages, media), not static files.
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
            relative = path.relative_to(self.output).as_posix()
            if relative in ('index.html', 'catalog/index.html'):
                expected.append({'type': 'module', 'src': '/assets/catalog.js'})
            elif relative in ('submit/index.html', 'submit/done/index.html'):
                expected.append({'type': 'module', 'src': '/assets/seeds.js'})
            elif relative.startswith('apps/'):
                expected.append({'type': 'module', 'src': '/assets/catalog.js'})
                expected.append({'type': 'module', 'src': '/assets/share.js'})
                expected.append({'type': 'module', 'src': '/assets/seed-media.js'})
                expected.append({'type': 'module', 'src': '/assets/social.js'})
            elif relative == 'account/index.html':
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
            self.assertIn('/brand/tiinyapp-farm-square-logo.png', doc.references)
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
            self.assertIn('>Reviewed<', html)
            self.assertIn('>Library<', html)
        app['verified'] = False
        app['entry'] = {'command': 'run'}
        html = SITE['badges'](app, TODAY)
        self.assertNotIn('>Reviewed<', html)
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
            self.assertIn('farm start fourth-seed', ' '.join(Document(text).text))
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
        expected = {'https://tiinyapp.farm' + path for path in ('/', '/catalog/', '/install/', '/submit/', '/docs/agents/', '/manifests/')}
        expected.update('https://tiinyapp.farm/apps/' + app['id'] + '/' for app in self.apps)
        self.assertEqual(urls, expected)
        self.assertIn('Sitemap: https://tiinyapp.farm/sitemap.xml', (self.output / 'robots.txt').read_text())
        schema = json.loads((ROOT / 'docs/manifest.schema.json').read_text())
        self.assertEqual(set(SITE['FIELDS']), set(schema['properties']))

    def test_locked_tokens_motion_and_phone_layout_constraints(self):
        css = (self.output / 'assets/site.css').read_text()
        actual = dict(re.findall(r'(--[a-z]+):(#[A-Fa-f0-9]{6})', css))
        self.assertEqual(actual, {'--night': '#090D14', '--soil': '#12171F', '--fence': '#1E2732',
                                  '--hay': '#F2C462', '--cyan': '#00C8F0', '--mint': '#7FE3DC',
                                  '--ink': '#E8EEF2', '--mute': '#9AA7B4', '--bad': '#F0A08F'})
        self.assertIn('white-space:pre-wrap', css)
        self.assertIn('overflow-wrap:anywhere', css)
        self.assertIn('minmax(min(300px,100%),1fr)', css)
        self.assertIn('animation:rise .3s ease-out forwards', css)
        self.assertIn('transition:background .15s ease-out,transform .15s ease-out', css)
        self.assertIn('@media(prefers-reduced-motion:reduce)', css)
        self.assertRegex(css, r'\.app \.two\{[^}]*grid-template-columns:minmax\(0,1fr\) 300px')
        self.assertRegex(css, r'@media\(max-width:760px\).*\.app \.two\{grid-template-columns:1fr')
        self.assertRegex(css, r'\.page\{[^}]*max-width:720px')
        self.assertRegex(css, r'\.stp \.n\{[^}]*width:32px;height:32px')

    def test_deploy_configuration(self):
        config = tomllib.loads((ROOT / 'wrangler.toml').read_text())
        self.assertEqual(config['name'], 'tiinyapp-farm')
        self.assertEqual(config['main'], 'worker/main.mjs')
        self.assertEqual(config['assets']['binding'], 'ASSETS')
        self.assertTrue(set(['/api/*', '/seeds-files/*', '/farm/*', '/makers/*', '/media/*', '/seeds/*']).issubset(config['assets']['run_worker_first']))
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

    def test_submit_form_has_v0_groups_release_choices_and_access_checkboxes(self):
        html = (self.output / 'submit/index.html').read_text()
        doc = Document(html)
        visible = ' '.join(doc.text)
        for phrase in ('Sign in', 'Verify you own a Tiiny', 'Your app', 'Send it again',
                       'Get my code', 'Submit for review', 'Your draft is saved on this computer as you type.'):
            self.assertIn(phrase, visible)
        legends = [' '.join(Document(text).text) for text in re.findall(r'<legend[^>]*>(.*?)</legend>', html)]
        for legend in ('About the app', 'Release', 'Links and images'):
            self.assertTrue(any(text.startswith(legend) for text in legends), legend)
        locked = [attrs.get('id') for tag, attrs in doc.tags if tag == 'fieldset' and 'disabled' in attrs]
        self.assertIn('proof-fields', locked)
        self.assertIn('seed-fields', locked)
        choices = [attrs for tag, attrs in doc.tags if tag == 'input' and attrs.get('type') == 'radio']
        self.assertEqual(len(choices), 2)
        self.assertEqual(len({attrs['name'] for attrs in choices}), 1)
        permissions = [attrs for tag, attrs in doc.tags if tag == 'input' and attrs.get('type') == 'checkbox']
        self.assertEqual({attrs['value'] for attrs in permissions}, {'microphone', 'files', 'network', 'device'})
        self.assertFalse(any(tag == 'select' and 'multiple' in attrs for tag, attrs in doc.tags))
        for phrase in ('This app uses', 'Microphone', 'Files', 'Network', 'Your Tiiny'):
            self.assertIn(phrase, visible)
        css = (self.output / 'assets/site.css').read_text()
        self.assertIn('max-width:560px', css)
        self.assertNotIn('.seed-form-grid{grid-template-columns:repeat(2', css)

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
            self.assertIn('/submit/', doc.references)
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
        form = Document((self.output / 'submit/index.html').read_text())
        self.assertTrue({'seed-icon', 'seed-header', 'seed-gallery', 'repo', 'video'}.issubset(form.ids))
        gallery = next(attrs for tag, attrs in form.tags if attrs.get('id') == 'seed-gallery')
        self.assertIn('multiple', gallery)

    def test_private_farm_shell_and_catalog(self):
        html = (self.output / 'account/index.html').read_text()
        doc = Document(html)
        self.assertTrue({'maker-name', 'maker-avatar', 'maker-bio', 'maker-links', 'maker-form',
                         'bio', 'avatar', 'github', 'website', 'youtube', 'my-seeds', 'refresh-seeds'}.issubset(doc.ids))
        inputs = {attrs['id']: attrs for tag, attrs in doc.tags if tag in ('input', 'textarea')}
        self.assertEqual(inputs['bio']['maxlength'], '600')
        self.assertEqual(inputs['avatar']['accept'], 'image/png,image/jpeg,image/webp')
        self.assertEqual(json.loads((self.output / 'catalog.json').read_text()), self.apps)
        self.assertIn('id="account-farm" href="/account/" hidden', (self.output / 'submit/index.html').read_text())

    def test_agent_guide_and_account_token_controls(self):
        guide = (ROOT / 'docs/agents.txt').read_text()
        self.assertEqual((self.output / 'llms.txt').read_text(), guide)
        page = (self.output / 'docs/agents/index.html').read_text()
        visible = ' '.join(Document(page).text)
        for phrase in ('what the farm is', 'farm publish', 'curl --fail-with-body', '/api/media',
                       '/api/seeds', 'farm.json', 'Ask the person for their token; never make one up.',
                       'pull request URL', 'https://tiinyapp.farm/account/'):
            self.assertIn(phrase.lower(), visible.lower())
        for field in ('id', 'name', 'pitch', 'description', 'version', 'license', 'category',
                      'entry', 'permissions', 'links', 'media'):
            self.assertRegex(guide, rf'(?m)^\* {field} ')
        account = Document((self.output / 'account/index.html').read_text())
        self.assertTrue({'api-tokens-heading', 'create-token', 'token-form', 'token-name',
                         'token-reveal', 'new-token', 'copy-token', 'token-status',
                         'api-tokens'}.issubset(account.ids))
        script = (self.output / 'assets/farm.js').read_text()
        for contract in ("api('/api/tokens')", "api('/api/tokens', post({ name:",
                         "api('/api/tokens/' + encodeURIComponent(token.id), { method: 'DELETE' })",
                         'navigator.clipboard.writeText'):
            self.assertIn(contract, script)

    def test_seed_tabs_control_three_panels_with_only_first_visible(self):
        doc = Document((self.output / 'submit/index.html').read_text())
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
        for label in ('1 · Sign in', '2 · Verify you own a Tiiny', '3 · Your app'):
            self.assertIn(label, doc.text)

    def test_literal_instructions_and_app_section_order(self):
        html = SITE['steps']()
        install = ' '.join(Document(html).text)
        for phrase in ('Python 3.9 or newer', 'macOS, Linux and Windows',
                       'pip install tiinyapp-farm', 'farm device',
                       'http://openai.api.tiiny/v1', 'http://<your-tiiny-ip>/v1',
                       'TiinyOS → Settings → API Key', '~/.tiinyapps/device.json',
                       'farm install titanium-tiiny-bot', 'farm start titanium-tiiny-bot',
                       'farm list', 'farm stop <id>', 'farm update <id>', 'farm remove <id>'):
            self.assertIn(phrase, install)
        steps = [attrs for tag, attrs in Document(html).tags if 'stp' in attrs.get('class', '').split()]
        self.assertEqual(len(steps), 3)
        self.assertEqual(sum(tag == 'dl' for tag, attrs in Document(html).tags), 2)
        submit = ''.join(Document(SITE['seeds']()).text)
        self.assertIn('Only Tiiny owners can submit apps. Your public TiinyVerse profile is the proof: '
                      'we give you a code, you put it in your bio, and we read it once. '
                      'Like a DNS TXT record.', submit)
        self.assertIn('Two short pages. The card on the right is what people will see in the catalog, '
                      'and it updates as you type.', submit)
        for app in self.apps:
            html = SITE['app_page'](app, TODAY)
            main, rail = html.split('<aside', 1)
            main_headings = re.findall(r'<h2[^>]*>(.*?)</h2>', main)
            self.assertEqual(main_headings[:2], ['Install', 'What it does'])
            self.assertIn('Comments', main_headings)
            self.assertEqual(re.findall(r'<h3[^>]*>(.*?)</h3>', rail)[:3], ['Needs', 'Release', 'Maker'])
            self.assertIn('id="seed-thumb"', rail)
            self.assertIn('data-share', rail)
            for port in app['requires']['ports']:
                self.assertIn('http://localhost:' + str(port), main)
        for path in self.output.rglob('*.html'):
            if path.relative_to(self.output).as_posix() == 'docs/agents/index.html':
                continue  # The public API route is /api/seeds and must be named literally for assistants.
            visible = ' '.join(Document(path.read_text()).text)
            self.assertNotRegex(visible, r'(?i)farmhand|\bsprouting\b|\bseeds?\b|My farm')

    def test_navigation_links_and_current_page(self):
        for path, active in [('index.html', '/'), ('install/index.html', '/install/'),
                             ('catalog/index.html', '/catalog/'), ('submit/index.html', '/submit/'),
                             ('apps/' + self.apps[0]['id'] + '/index.html', '/')]:
            html = (self.output / path).read_text()
            nav = re.search(r'<nav\b[^>]*>(.*?)</nav>', html, re.S).group(1)
            doc = Document(nav)
            anchors = [attrs for tag, attrs in doc.tags if tag == 'a']
            self.assertEqual([attrs['href'] for attrs in anchors[:4]], ['/', '/catalog/', '/install/', '/submit/'])
            current = [attrs for attrs in anchors if attrs.get('aria-current') == 'page']
            self.assertEqual([attrs['href'] for attrs in current], [active])
            self.assertIn('on', current[0].get('class', '').split())
            self.assertIn('Sign in', ''.join(doc.text))
            self.assertIn('/submit/', doc.references)

    def test_catalog_categories_and_safe_text_module(self):
        html = (self.output / 'catalog/index.html').read_text()
        doc = Document(html)
        self.assertIn('catalog-categories', doc.ids)
        chips = [attrs for tag, attrs in doc.tags if tag == 'button' and 'cat' in attrs.get('class', '').split()]
        self.assertEqual([''.join(Document(re.findall(r'<button[^>]*class="cat"[^>]*>(.*?)</button>', html)[i]).text)
                          for i in range(len(chips))], ['All', 'Assistants', 'Family', 'Audio', 'Developer tools', 'Libraries'])
        config = json.loads((self.output / 'categories.json').read_text())
        self.assertEqual(config['order'], ['Assistants', 'Family', 'Audio', 'Developer tools', 'Libraries'])
        self.assertEqual(config['map']['benchmark'], 'Developer tools')
        source = (ROOT / 'site/assets/catalog.js').read_text()
        self.assertNotIn('innerHTML', source)
        self.assertNotIn('insertAdjacentHTML', source)
        script = r'''import assert from 'node:assert/strict';
const module = await import(process.argv[1]);
globalThis.document = { createElement: tag => ({ tag, className: '', textContent: '' }) };
const hostile = '<img src=x onerror=alert(1)> & text';
const element = module.textElement('p', 'pitch', hostile);
assert.equal(element.textContent, hostile);
assert.equal(element.className, 'pitch');
'''
        result = subprocess.run(['node', '--input-type=module', '-e', script,
                                 (ROOT / 'site/assets/catalog.js').as_uri()], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_works_outside_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/build-site.py'), '--output', str(Path(temp) / 'dist'), '--today', TODAY.isoformat()], cwd=temp, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f'Built {len(self.apps)} app pages', result.stdout)


if __name__ == '__main__':
    unittest.main()
