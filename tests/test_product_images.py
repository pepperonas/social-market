"""
Product cover serving.

Two defects lived here:

1. Nothing served product images at all -- there was no route -- and the
   templates interpolated `product.images[0]`, a ProductImage *object*, straight
   into a src attribute. The feature had never worked.
2. Once it did work, the app's own global rate limit (10/s) throttled it: a
   listing page references twenty covers, so half of them came back 429 and the
   page rendered with blank tiles. A rate limit exists to bound expensive or
   abusable work; applied to static bytes it is a self-inflicted outage.
"""

import io
import os
import uuid

import pytest
from PIL import Image

from app.services.cover_service import cover_filename, render_cover


@pytest.fixture
def product_with_cover(app, sample_vendor):
    from app import db
    from app.models.product import Product, ProductCategory, ProductImage

    suffix = uuid.uuid4().hex[:8]
    category = ProductCategory(id=uuid.uuid4(), name=f'C {suffix}', slug=f'c-{suffix}')
    db.session.add(category)
    db.session.flush()

    product = Product(
        id=uuid.uuid4(), vendor_id=sample_vendor.id, category_id=category.id,
        title=f'Covered Product {suffix}', description='d', price=10,
        quantity=5, is_active=True, is_approved=True,
    )
    db.session.add(product)
    db.session.flush()

    folder = os.path.join(app.config['UPLOAD_FOLDER'], 'products')
    os.makedirs(folder, exist_ok=True)
    filename = cover_filename(product.title)
    with open(os.path.join(folder, filename), 'wb') as handle:
        handle.write(render_cover(product.title))

    image = ProductImage(
        product_id=product.id, filename=filename,
        filepath=os.path.join(folder, filename),
        file_size=1, mime_type='image/png', is_primary=True, display_order=0,
    )
    db.session.add(image)
    db.session.commit()

    yield product, filename

    for obj in (image, product, category):
        try:
            db.session.delete(obj)
            db.session.commit()
        except Exception:
            db.session.rollback()
    try:
        os.remove(os.path.join(folder, filename))
    except OSError:
        pass


class TestImageUrl:
    def test_product_without_image_has_no_url(self, app, sample_vendor):
        from app import db
        from app.models.product import Product, ProductCategory

        suffix = uuid.uuid4().hex[:8]
        category = ProductCategory(id=uuid.uuid4(), name=f'N {suffix}', slug=f'n-{suffix}')
        db.session.add(category)
        db.session.flush()
        product = Product(
            id=uuid.uuid4(), vendor_id=sample_vendor.id, category_id=category.id,
            title='No Cover', description='d', price=1, quantity=1,
        )
        db.session.add(product)
        db.session.commit()

        with app.test_request_context('/'):
            assert product.primary_image_url is None

        db.session.delete(product)
        db.session.delete(category)
        db.session.commit()

    def test_url_points_at_the_media_route(self, app, product_with_cover):
        product, filename = product_with_cover

        with app.test_request_context('/'):
            url = product.primary_image_url

        assert url and filename in url
        assert '/media/products/' in url

    def test_templates_never_render_the_orm_object(self):
        """`{{ product.images[0] }}` renders a repr, not a URL."""
        import pathlib

        offenders = []
        for path in pathlib.Path('app/templates').rglob('*.html'):
            if 'product.images[0]' in path.read_text():
                offenders.append(path.name)

        assert not offenders, f'use product.primary_image_url instead: {offenders}'


class TestServing:
    def test_existing_cover_is_served(self, client, product_with_cover):
        _, filename = product_with_cover
        response = client.get(f'/media/products/{filename}')

        assert response.status_code == 200
        assert response.mimetype == 'image/png'

    def test_served_bytes_are_a_valid_image(self, client, product_with_cover):
        _, filename = product_with_cover
        data = client.get(f'/media/products/{filename}').get_data()

        assert Image.open(io.BytesIO(data)).size[0] > 0

    def test_unknown_file_is_404(self, client):
        assert client.get('/media/products/nope.png').status_code == 404

    @pytest.mark.parametrize('attempt', [
        '../../../etc/passwd',
        '..%2f..%2fetc%2fpasswd',
        'sub/dir/file.png',
        'file with spaces.png',
        'file;rm -rf.png',
    ])
    def test_path_traversal_is_refused(self, client, attempt):
        """
        send_from_directory would also refuse these, but the filename is matched
        against a strict pattern first, so the attempt never reaches the disk.
        """
        response = client.get(f'/media/products/{attempt}')
        assert response.status_code in (301, 308, 404), (
            f'{attempt!r} returned {response.status_code}'
        )

    def test_response_is_cacheable(self, client, product_with_cover):
        """Covers are immutable per title; re-fetching them every time is waste."""
        _, filename = product_with_cover
        response = client.get(f'/media/products/{filename}')

        assert 'max-age' in response.headers.get('Cache-Control', '')


class TestNotRateLimited:
    """
    A listing page pulls ~20 covers at once. Under the default 10/s limit half of
    them returned 429 and the page rendered with blank tiles.
    """

    def test_media_route_is_exempt(self):
        import pathlib

        source = pathlib.Path('app/routes/marketplace.py').read_text()
        block = source[source.index("route('/media/products"):]
        head = block[:block.index('def product_image')]

        assert 'limiter.exempt' in head, (
            'the media route must be exempt from the global rate limit'
        )

    def test_many_requests_all_succeed(self, app, client, product_with_cover):
        """Exercise it, not just the decorator."""
        _, filename = product_with_cover
        app.config['RATELIMIT_ENABLED'] = True

        codes = [client.get(f'/media/products/{filename}').status_code for _ in range(25)]

        assert codes.count(200) == 25, f'throttled its own images: {set(codes)}'
