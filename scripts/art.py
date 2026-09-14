#!/usr/bin/env python3
"""Draw house art for one app and write it beside the rest of the shelf.

    OPENAI_API_KEY=... python3 scripts/art.py <app-id> "<one sentence describing the scene>"

For apps the maintainers draw themselves. Makers use the Generate art button on the site, which
runs the same two prompts through the Worker. The key is read from the environment and from
nowhere else: never a file, never an argument, never printed.
"""

import argparse
import base64
import io
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from farm import art  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SHELF = ROOT / 'site/assets/art'
ENDPOINT = 'https://api.openai.com/v1/images/generations'
TIMEOUT = 300


def requests(scene):
    """The two request bodies, exactly as the Worker sends them."""
    return {
        'header': {
            'model': art.MODEL, 'prompt': art.header_prompt(scene), 'n': 1,
            'quality': art.QUALITY, 'size': art.HEADER_SIZE,
            'output_format': 'webp', 'output_compression': 82,
        },
        'icon': {
            'model': art.MODEL, 'prompt': art.icon_prompt(scene), 'n': 1,
            'quality': art.QUALITY, 'size': art.ICON_SIZE,
            'output_format': 'png', 'background': 'transparent',
        },
    }


def targets(app_id):
    """Where the two files land."""
    return {'header': SHELF / f'{app_id}-header.webp', 'icon': SHELF / f'{app_id}-icon.png'}


def draw(body, key):
    """One image, returned as bytes, with the reported output tokens."""
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode('utf-8'),
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        # The body can carry account and request detail, so only the status is repeated.
        raise SystemExit(f'The drawing service answered {error.code}.') from None
    except urllib.error.URLError as error:
        raise SystemExit(f'The drawing service could not be reached: {error.reason}') from None
    images = payload.get('data') or []
    if not images or not images[0].get('b64_json'):
        raise SystemExit('The drawing service returned no image.')
    usage = payload.get('usage') or {}
    return base64.b64decode(images[0]['b64_json']), usage.get('output_tokens', 0)


def shrink_icon(data, pixels=art.ICON_PIXELS):
    """The shelf keeps icons at 512; the API's smallest square is 1024."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        if image.size == (pixels, pixels):
            return data
        small = image.convert('RGBA').resize((pixels, pixels), Image.LANCZOS)
        buffer = io.BytesIO()
        small.save(buffer, format='PNG')
        return buffer.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Draw one app's header and icon in the house style.")
    parser.add_argument('app_id', help='the manifest id, such as tiiny-bench')
    parser.add_argument('scene', help='one sentence describing what is in the picture')
    parser.add_argument('--print-prompts', action='store_true', help='show the two prompts and stop')
    options = parser.parse_args(argv)

    bodies = requests(options.scene)
    if options.print_prompts:
        for kind, body in bodies.items():
            print(f'--- {kind} ---\n{body["prompt"]}\n')
        return 0

    key = os.environ.get('OPENAI_API_KEY', '')
    if not key:
        raise SystemExit('Set OPENAI_API_KEY in the environment first.')

    paths = targets(options.app_id)
    SHELF.mkdir(parents=True, exist_ok=True)
    tokens = 0
    for kind, body in bodies.items():
        data, spent = draw(body, key)
        tokens += spent
        if kind == 'icon':
            data = shrink_icon(data)
        paths[kind].write_bytes(data)
        print(f'{paths[kind].relative_to(ROOT)}  {len(data)} bytes')
    if tokens:
        print(f'{tokens} image output tokens, about ${tokens * 30 / 1_000_000:.3f} at 30 USD per million')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
