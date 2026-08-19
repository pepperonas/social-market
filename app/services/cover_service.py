"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Product Cover Generator
Purpose: Give seeded demo products real images without shipping stock photos

Why generated art rather than downloaded pictures:
    A training repository that bundles photographs inherits their licences and
    their EXIF. Drawing the covers means the repo carries no third-party media,
    every file's provenance is a function in this file, and the images contain
    no metadata to strip -- which is a useful contrast to the upload path, where
    stripping EXIF is exactly the job (see image_service.py).

Deterministic by design: the same title always produces the same cover, so
re-seeding does not churn the demo and screenshots stay reproducible.
"""

import colorsys
import hashlib
import io

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 800, 600

# Candidate fonts, most-preferred first. Falls back to PIL's bitmap font, which
# is ugly but always present -- a missing font must not break seeding.
FONT_CANDIDATES = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    '/Library/Fonts/Arial.ttf',
)


def _seed(title):
    """Stable integer seed derived from the title."""
    return int(hashlib.sha256(title.encode('utf-8')).hexdigest()[:12], 16)


def _palette(seed):
    """
    Two related hues plus a light ink colour.

    Generated in HSV so the pair is always harmonious and the contrast against
    the text is predictable, rather than hoping random RGB happens to work.
    """
    hue = (seed % 360) / 360.0
    shift = 0.08 + ((seed >> 8) % 12) / 100.0

    top = colorsys.hsv_to_rgb(hue, 0.62, 0.42)
    bottom = colorsys.hsv_to_rgb((hue + shift) % 1.0, 0.72, 0.20)
    accent = colorsys.hsv_to_rgb((hue + 0.5) % 1.0, 0.45, 0.95)

    to_255 = lambda c: tuple(int(round(v * 255)) for v in c)  # noqa: E731
    return to_255(top), to_255(bottom), to_255(accent)


def _load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _gradient(draw, top, bottom):
    """Vertical gradient, one line at a time."""
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        draw.line(
            [(0, y), (WIDTH, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )


def _motif(draw, seed, accent):
    """
    An abstract motif so covers are distinguishable at thumbnail size.

    Three variants keyed off the seed; the point is visual variety in a grid of
    products, not representing the product.

    ``accent`` already carries an alpha channel -- do not append another, or
    Pillow rejects the 5-tuple. Only every third title hits the arc variant, so
    that mistake stays invisible until it does not.
    """
    variant = seed % 3
    rnd = seed

    if variant == 0:  # concentric arcs
        for i in range(7):
            r = 90 + i * 55
            box = (WIDTH - 180 - r, HEIGHT - 120 - r, WIDTH - 180 + r, HEIGHT - 120 + r)
            draw.arc(box, start=200, end=340, fill=accent, width=3)
    elif variant == 1:  # scattered dots on a grid
        for row in range(6):
            for col in range(9):
                rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
                if rnd % 3:
                    continue
                x, y = 70 + col * 80, 90 + row * 80
                r = 6 + (rnd >> 5) % 14
                draw.ellipse((x - r, y - r, x + r, y + r), fill=accent)
    else:  # diagonal bars
        for i in range(14):
            rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
            x = -200 + i * 90
            w = 8 + (rnd >> 7) % 22
            draw.polygon(
                [(x, HEIGHT), (x + 260, 0), (x + 260 + w, 0), (x + w, HEIGHT)],
                fill=accent,
            )


def _wrap(draw, text, font, max_width):
    """Greedy word wrap against the measured pixel width."""
    words, lines, current = text.split(), [], ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_cover(title, subtitle=None):
    """
    Draw a cover for ``title``.

    Args:
        title: Product title, also the seed for colours and motif
        subtitle: Optional second line, e.g. the category

    Returns:
        bytes: PNG data
    """
    seed = _seed(title)
    top, bottom, accent = _palette(seed)

    image = Image.new('RGB', (WIDTH, HEIGHT), top)
    draw = ImageDraw.Draw(image, 'RGBA')

    _gradient(draw, top, bottom)

    # Motif on its own translucent layer so it reads as texture, not foreground
    overlay = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    _motif(ImageDraw.Draw(overlay), seed, accent + (38,))
    image = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(image, 'RGBA')

    title_font = _load_font(52)
    small_font = _load_font(24)

    lines = _wrap(draw, title, title_font, WIDTH - 120)[:3]

    # Centre the text band vertically. Listing cards crop these covers to a wide
    # strip with object-fit: cover, which keeps the MIDDLE of the image -- a
    # title anchored to the bottom edge simply disappears in the grid.
    line_height = 62
    block_height = len(lines) * line_height + (34 if subtitle else 0)
    band_top = (HEIGHT - block_height) // 2 - 26

    # Scrim behind the text: the gradient alone cannot guarantee contrast for
    # every hue, and unreadable text on a pretty background is still unreadable.
    draw.rectangle(
        (0, band_top - 18, WIDTH, band_top + block_height + 26), fill=(0, 0, 0, 130)
    )

    y = band_top
    for line in lines:
        draw.text((60, y), line, font=title_font, fill=(255, 255, 255))
        y += line_height

    if subtitle:
        draw.text((60, y + 4), subtitle.upper(), font=small_font, fill=accent)

    # Corner marker, so a cover is never mistaken for a real product photo
    draw.text((WIDTH - 190, 28), 'DEMO ASSET', font=small_font, fill=(255, 255, 255, 150))

    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()


def cover_filename(title):
    """Stable, filesystem-safe name for a title's cover."""
    digest = hashlib.sha256(title.encode('utf-8')).hexdigest()[:16]
    return f'cover-{digest}.png'


__all__ = ['render_cover', 'cover_filename', 'WIDTH', 'HEIGHT']
