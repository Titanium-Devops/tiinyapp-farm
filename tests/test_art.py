"""The house style is one set of strings. Both the Worker and the maintainer script use them."""

import json
from pathlib import Path
import runpy
import unittest

from farm import art

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/art-prompts.json').read_text(encoding='utf-8'))


class PromptTests(unittest.TestCase):
    def test_fixed_scenes_produce_fixed_prompts(self):
        for case in FIXTURE['cases']:
            with self.subTest(scene=case['scene']):
                self.assertEqual(art.clean_scene(case['scene']), case['clean'])
                self.assertEqual(art.header_prompt(case['scene']), case['header'])
                self.assertEqual(art.icon_prompt(case['scene']), case['icon'])

    def test_fixture_records_the_model_and_sizes_the_worker_uses(self):
        self.assertEqual(FIXTURE['model'], art.MODEL)
        self.assertEqual(FIXTURE['headerSize'], art.HEADER_SIZE)
        self.assertEqual(FIXTURE['iconSize'], art.ICON_SIZE)
        self.assertEqual(FIXTURE['quality'], art.QUALITY)
        self.assertEqual(FIXTURE['maxScene'], art.MAX_SCENE)
        self.assertEqual(FIXTURE['minScene'], art.MIN_SCENE)

    def test_refused_scenes_are_refused(self):
        for scene in FIXTURE['refused']:
            with self.subTest(scene=scene[:20]):
                with self.assertRaises(art.SceneError):
                    art.header_prompt(scene)

    def test_a_scene_line_is_collapsed_to_one_sentence(self):
        self.assertEqual(art.clean_scene('  two   lines\nof   words  '), 'two lines of words.')
        self.assertEqual(art.clean_scene('already ends in a question?'), 'already ends in a question?')
        self.assertEqual(art.clean_scene('x' * art.MAX_SCENE), 'x' * art.MAX_SCENE + '.')

    def test_the_scene_is_framed_by_the_style_and_the_rules(self):
        prompt = art.header_prompt('a lantern on a bench')
        self.assertTrue(prompt.startswith(art.STYLE))
        self.assertIn('The scene: a lantern on a bench.', prompt)
        self.assertTrue(prompt.endswith(art.NEGATIVE))
        self.assertIn(art.HEADER_FRAME, prompt)
        self.assertNotIn(art.ICON_FRAME, prompt)

    def test_the_icon_prompt_asks_for_a_transparent_sticker(self):
        prompt = art.icon_prompt('a lantern on a bench')
        self.assertIn('fully transparent background', prompt)
        self.assertIn('sticker', prompt)
        self.assertIn(art.ICON_FRAME, prompt)
        self.assertNotIn(art.HEADER_FRAME, prompt)

    def test_no_prompt_ever_invites_lettering(self):
        for builder in (art.header_prompt, art.icon_prompt):
            prompt = builder('a signpost beside a gate')
            self.assertIn('Never include text, letters, numbers, logos', prompt)


class StyleDocumentTests(unittest.TestCase):
    def test_the_written_style_carries_the_palette_the_prompts_use(self):
        text = (ROOT / 'docs/ART-STYLE.md').read_text(encoding='utf-8')
        for value in ('#090D14', '#00C8F0', '1536x1024', '1024x1024'):
            self.assertIn(value, text)
        self.assertIn('Tiiny', text)
        self.assertNotIn('\u2014', text)

    def test_the_art_page_is_part_of_the_documentation(self):
        page = (ROOT / 'docs/site/10-art.md').read_text(encoding='utf-8')
        self.assertIn('slug: art', page)
        self.assertIn('order: 10', page)
        for other in ('docs/site/04-publish.md', 'docs/site/05-manifest.md'):
            self.assertIn('/docs/art/', (ROOT / other).read_text(encoding='utf-8'))


class MaintainerScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = runpy.run_path(str(ROOT / 'scripts/art.py'))

    def test_the_script_builds_the_same_two_prompts(self):
        requests = self.script['requests']('a bench of glowing gauges')
        self.assertEqual(requests['header']['prompt'], art.header_prompt('a bench of glowing gauges'))
        self.assertEqual(requests['icon']['prompt'], art.icon_prompt('a bench of glowing gauges'))

    def test_the_script_asks_for_the_sizes_and_formats_the_shelf_uses(self):
        requests = self.script['requests']('a bench of glowing gauges')
        self.assertEqual(requests['header']['size'], art.HEADER_SIZE)
        self.assertEqual(requests['header']['output_format'], 'webp')
        self.assertEqual(requests['icon']['size'], art.ICON_SIZE)
        self.assertEqual(requests['icon']['output_format'], 'png')
        self.assertEqual(requests['icon']['background'], 'transparent')
        for request in requests.values():
            self.assertEqual(request['model'], art.MODEL)
            self.assertEqual(request['quality'], art.QUALITY)
            self.assertEqual(request['n'], 1)

    def test_the_script_writes_beside_the_existing_shelf_art(self):
        paths = self.script['targets']('tiiny-bench')
        self.assertTrue(str(paths['header']).endswith('site/assets/art/tiiny-bench-header.webp'))
        self.assertTrue(str(paths['icon']).endswith('site/assets/art/tiiny-bench-icon.png'))

    def test_the_script_reads_the_key_from_the_environment_only(self):
        source = (ROOT / 'scripts/art.py').read_text(encoding='utf-8')
        self.assertIn("os.environ.get('OPENAI_API_KEY', '')", source)
        for elsewhere in ('.api_keys', 'read_text', 'getpass', 'add_argument(\'--key'):
            self.assertNotIn(elsewhere, source)

    def test_the_script_never_prints_the_key(self):
        source = (ROOT / 'scripts/art.py').read_text(encoding='utf-8')
        for line in source.splitlines():
            if 'print(' in line:
                self.assertNotIn('key', line)


if __name__ == '__main__':
    unittest.main()
