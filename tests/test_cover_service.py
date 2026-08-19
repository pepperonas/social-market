"""
Tests for the generated product covers.

Covers are drawn rather than downloaded, which is a deliberate supply-chain
choice: no third-party media in the repository, no licences to track, and no
EXIF to leak. These tests hold that choice to its promises -- deterministic
output, real PNGs, readable text, and no metadata riding along.
"""

import io

import pytest
from PIL import Image

from app.services.cover_service import HEIGHT, WIDTH, cover_filename, render_cover


class TestOutputIsARealImage:
    def test_returns_png_bytes(self):
        data = render_cover('Cybersecurity Handbook')
        assert data[:8] == b'\x89PNG\r\n\x1a\n', 'must be a real PNG, not a stub'

    def test_has_the_declared_dimensions(self):
        image = Image.open(io.BytesIO(render_cover('Anything')))
        assert image.size == (WIDTH, HEIGHT)

    def test_is_rgb_not_palette(self):
        """Gradients in palette mode band badly."""
        assert Image.open(io.BytesIO(render_cover('Anything'))).mode == 'RGB'

    def test_size_is_reasonable_for_a_repository(self):
        data = render_cover('Machine Learning Course')
        assert len(data) < 400_000, f'{len(data)} bytes is too heavy to commit'


class TestNoMetadataRidesAlong:
    """
    A drawn image has nothing to strip -- but assert it, because the day someone
    swaps in a photograph is the day this file starts leaking camera and GPS
    data into a public repository.
    """

    def test_carries_no_exif(self):
        image = Image.open(io.BytesIO(render_cover('Whatever')))
        assert not image.getexif(), 'generated covers must not carry EXIF'

    def test_carries_no_text_chunks(self):
        image = Image.open(io.BytesIO(render_cover('Whatever')))
        assert not getattr(image, 'text', None)


class TestDeterminism:
    """Re-seeding must not churn the demo or invalidate screenshots."""

    def test_same_title_gives_identical_bytes(self):
        assert render_cover('Stable Title') == render_cover('Stable Title')

    def test_different_titles_give_different_images(self):
        assert render_cover('Alpha Product') != render_cover('Beta Product')

    def test_filename_is_stable(self):
        assert cover_filename('Some Title') == cover_filename('Some Title')

    def test_filename_differs_per_title(self):
        assert cover_filename('Alpha') != cover_filename('Beta')

    @pytest.mark.parametrize('title', [
        '../../etc/passwd',
        'Title With Spaces',
        'Ünïcödé Prödüct',
        'quote"and\'apostrophe',
        'semi;colon&amp',
    ])
    def test_filename_is_always_filesystem_safe(self, title):
        """The title reaches this from seed data; it must not steer the path."""
        import re

        name = cover_filename(title)
        assert re.fullmatch(r'cover-[0-9a-f]{16}\.png', name), name
        assert '/' not in name and '..' not in name


class TestVisualQuality:
    def test_image_is_not_blank(self):
        image = Image.open(io.BytesIO(render_cover('Some Product')))
        assert len(image.getcolors(maxcolors=200_000) or []) > 50, 'looks blank'

    def test_text_area_is_dark_enough_for_white_text(self):
        """
        The title sits on a scrim precisely because a light gradient would make
        white text unreadable. Check the region the text actually occupies.
        """
        image = Image.open(io.BytesIO(render_cover('A Fairly Long Product Title Here')))
        band = image.crop((0, HEIGHT - 200, WIDTH, HEIGHT - 60))
        pixels = list(band.getdata())
        mean_luma = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in pixels) / len(pixels)

        assert mean_luma < 110, f'text band too light ({mean_luma:.0f}) for white text'

    def test_long_titles_do_not_overflow(self):
        """Wrapping is measured in pixels; a very long title must still render."""
        data = render_cover('An Extraordinarily Long Product Title That Goes On And On Forever')
        assert Image.open(io.BytesIO(data)).size == (WIDTH, HEIGHT)

    def test_marked_as_a_demo_asset(self):
        """A generated cover must never be mistaken for a real product photo."""
        import pathlib

        source = pathlib.Path('app/services/cover_service.py').read_text()
        assert 'DEMO ASSET' in source

    def test_subtitle_is_optional(self):
        assert render_cover('No Subtitle Here') != render_cover('No Subtitle Here', 'Category')
