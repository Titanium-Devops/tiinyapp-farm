"""Exercise the share interaction with Node DOM fakes; never start a browser."""

from pathlib import Path
import subprocess
import runpy
import tempfile
from unittest.mock import patch
from PIL import ImageDraw
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('site/assets/share.js', 'utf8');
function setup({ navigator = {}, canonical = 'https://tiinyapp.farm/apps/seed/', dataset = { shareTitle: 'A seed', shareText: 'Grown by Fern' } } = {}) {
  const status = { textContent: '' }, timers = new Map();
  let click, nextTimer = 1;
  const button = {
    dataset,
    parentElement: { querySelector: () => status },
    addEventListener(name, listener) { assert.equal(name, 'click'); click = listener; },
  };
  vm.runInNewContext(source, {
    document: {
      title: 'The farm',
      querySelectorAll(selector) { assert.equal(selector, '[data-share]'); return [button]; },
      querySelector(selector) { assert.equal(selector, 'link[rel="canonical"]'); return canonical ? { href: canonical } : null; },
    },
    location: { href: 'https://tiinyapp.farm/makers/fern/?from=share' },
    navigator,
    setTimeout(callback, delay) { const id = nextTimer++; timers.set(id, { callback, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  return { click: () => click(), status, timers };
}
"""


class ShareTests(unittest.TestCase):
    def run_js(self, case):
        result = subprocess.run(
            ['node', '-e', HARNESS + '\n(async () => {\n' + case + '\n})().catch(error => { console.error(error); process.exitCode = 1; });'],
            cwd=ROOT, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sprouting_card_places_state_under_pitch(self):
        render = runpy.run_path(str(ROOT / 'scripts/share-cards.py'))['render_card']
        drawn = []
        original = ImageDraw.ImageDraw.text
        def capture(draw, xy, text, *args, **kwargs):
            drawn.append((xy, text))
            return original(draw, xy, text, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory, patch.object(ImageDraw.ImageDraw, 'text', capture):
            render(ROOT, Path(directory) / 'card.png', name='Test seed', pitch='A growing seed', maker='Fern', sprouting=True)
        pitch = next(xy for xy, text in drawn if text == 'A growing seed')
        state = next(xy for xy, text in drawn if text == 'Sprouting')
        self.assertGreater(state[1], pitch[1])
        self.assertLess(state[1], 459)

    def test_native_share_uses_title_text_and_canonical_url(self):
        self.run_js(r"""
let shared;
const view = setup({ navigator: {
  share: async data => { shared = JSON.parse(JSON.stringify(data)); },
  clipboard: { writeText() { assert.fail('Native sharing must not copy the URL'); } },
} });
await view.click();
assert.deepEqual(shared, { title: 'A seed', text: 'Grown by Fern', url: 'https://tiinyapp.farm/apps/seed/' });
assert.equal(view.status.textContent, '');
assert.equal(view.timers.size, 0);
""")

    def test_clipboard_fallback_clears_status_after_two_seconds(self):
        self.run_js(r"""
const copied = [];
const view = setup({ navigator: { clipboard: { writeText: async url => copied.push(url) } } });
await view.click();
assert.deepEqual(copied, ['https://tiinyapp.farm/apps/seed/']);
assert.equal(view.status.textContent, 'Link copied');
assert.equal(view.timers.size, 1);
let timer = [...view.timers.values()][0];
assert.equal(timer.delay, 2000);
await view.click();
assert.equal(view.timers.size, 1, 'A new click replaces the previous status timer');
timer = [...view.timers.values()][0];
assert.equal(timer.delay, 2000);
timer.callback();
assert.equal(view.status.textContent, '');
""")

    def test_missing_canonical_and_dataset_use_page_defaults(self):
        self.run_js(r"""
let shared;
const view = setup({ canonical: null, dataset: {}, navigator: { share: async data => { shared = JSON.parse(JSON.stringify(data)); } } });
await view.click();
assert.deepEqual(shared, { title: 'The farm', text: '', url: 'https://tiinyapp.farm/makers/fern/?from=share' });
""")

    def test_native_share_cancellation_is_silent(self):
        self.run_js(r"""
const view = setup({ navigator: {
  share: async () => { throw Object.assign(new Error('User cancelled'), { name: 'AbortError' }); },
  clipboard: { writeText() { assert.fail('Cancellation must not copy the URL'); } },
} });
view.status.textContent = 'An old status';
await view.click();
assert.equal(view.status.textContent, '');
assert.equal(view.timers.size, 0);
""")

    def test_clipboard_failure_explains_manual_copy(self):
        self.run_js(r"""
for (const navigator of [{ clipboard: { writeText: async () => { throw new Error('Permission denied'); } } }, {}]) {
  const view = setup({ navigator });
  await view.click();
  assert.equal(view.status.textContent, 'Could not share. Copy the URL from your address bar.');
  assert.equal(view.timers.size, 0);
}
""")


if __name__ == '__main__':
    unittest.main()
