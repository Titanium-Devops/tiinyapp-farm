"""Pillow share cards, using the same renderer for seeds and maker snapshots."""
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import warnings

from PIL import Image, ImageDraw, ImageFont, ImageOps

MIDNIGHT = '#090D14'
INK = '#E8EEF2'
MINT = '#7FE3DC'


def font(source, family, size):
    path = source / 'site/fonts' / (family + '.ttf')
    if not path.exists():
        warnings.warn(f'{family}.ttf unavailable; falling back to DejaVu')
        path = source / 'site/fonts' / ('DejaVuSerif-Bold.ttf' if family == 'Fraunces' else 'DejaVuSans.ttf')
    face = ImageFont.truetype(str(path), size)
    if family == 'Fraunces':  # variable font: pick the Bold instance for headings
        try: face.set_variation_by_name('Bold')
        except (OSError, AttributeError): pass
    return face


def picture(source, value):
    """Use checked-in site media first; bound optional remote image downloads."""
    if not value:
        return None
    try:
        url = urlsplit(value)
        if not url.netloc or url.netloc == 'tiinyapp.farm':
            relative = url.path.lstrip('/')
            root = source if relative.startswith('brand/') else source / 'site'
            local = (root / relative).resolve()
            if local.is_relative_to(root.resolve()) and local.is_file():
                with Image.open(local) as image:
                    return image.convert('RGB')
        if url.scheme != 'https':
            return None
        with urlopen(Request(value, headers={'User-Agent': 'tiinyapp-farm-build'}), timeout=5) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError('image exceeds 8 MiB')
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError('image exceeds 20 megapixels')
            return image.convert('RGB')
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        warnings.warn(f'Card image unavailable ({value}): {error}')
        return None


def wrapped(draw, text, face, width, limit):
    words = ' '.join(str(text).split()).split(' ')
    lines = []
    line = ''
    for word in words:
        candidate = (line + ' ' + word).strip()
        if draw.textlength(candidate, font=face) <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    lines = lines[:limit]
    # Ellipsize long individual words and the final truncated line.
    for index, line in enumerate(lines):
        truncated = draw.textlength(line, font=face) > width
        if index == limit - 1 and ' '.join(lines) != ' '.join(str(text).split()):
            truncated = True
        if truncated:
            while line and draw.textlength(line + '…', font=face) > width:
                line = line[:-1]
            lines[index] = line.rstrip() + '…'
    return lines


def render_card(source, target, *, name, pitch, maker, media=None, avatar=None, verified=False, sprouting=False):
    source, target = Path(source), Path(target)
    sprout = picture(source, '/brand/icon-512.png')
    media = media or {}
    artwork = picture(source, media.get('header')) or picture(source, media.get('icon')) or sprout
    canvas = Image.new('RGB', (1200, 630), MIDNIGHT)
    left = ImageOps.fit(artwork, (650, 630), method=Image.Resampling.LANCZOS)
    mask = Image.new('L', (650, 630))
    # Solid artwork on the left, smoothly fading into Midnight at the center.
    mask.putdata([round(255 * (1 - max(0, min(1, (x - 360) / 290))) ** 2)
                  for y in range(630) for x in range(650)])
    canvas.paste(left, (0, 0), mask)
    draw = ImageDraw.Draw(canvas)
    heading = font(source, 'Fraunces', 54)
    body = font(source, 'Nunito', 27)
    small = font(source, 'Nunito', 23)
    draw.text((644, 52), 'GROWN ON TIINY', font=font(source, 'Nunito', 17), fill=MINT)
    y = 100
    for line in wrapped(draw, name, heading, 510, 3):
        draw.text((640, y), line, font=heading, fill=INK)
        y += 64
    y += 18
    for line in wrapped(draw, pitch, body, 510, 2 if sprouting else 3):
        draw.text((644, y), line, font=body, fill='#9AA7B4')
        y += 36
    if sprouting:
        draw.text((644, y + 4), 'Sprouting', font=small, fill='#C5AF7D')
    portrait = ImageOps.fit(picture(source, avatar) or sprout, (52, 52), method=Image.Resampling.LANCZOS)
    circle = Image.new('L', (52, 52))
    ImageDraw.Draw(circle).ellipse((0, 0, 51, 51), fill=255)
    canvas.paste(portrait, (644, 462), circle)
    attribution = wrapped(draw, 'Grown by ' + maker, small, 444, 1)[0]
    draw.text((710, 459), attribution, font=small, fill=INK)
    if verified:
        draw.rounded_rectangle((710, 496, 845, 522), radius=13, fill='#1E2732')
        # Nunito has no check glyph; draw a small one.
        draw.line([(722, 505), (728, 511), (740, 497)], fill=MINT, width=3, joint='curve')
        draw.text((748, 497), 'Verified Tiiny', font=font(source, 'Nunito', 16), fill=MINT)
    mark = ImageOps.fit(sprout, (38, 38), method=Image.Resampling.LANCZOS)
    mark_mask = Image.new('L', (38, 38))
    ImageDraw.Draw(mark_mask).ellipse((0, 0, 37, 37), fill=255)
    canvas.paste(mark, (922, 559), mark_mask)
    draw.text((972, 562), 'tiinyapp.farm', font=small, fill=INK)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, 'PNG', optimize=True)
