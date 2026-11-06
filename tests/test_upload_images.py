"""
Review round 3 (2026-11), step 6: product image uploads, end to end.

Two findings, both invisible until an image is uploaded through the route and
then fetched through the URL the shop renders:

* Uploads were stored under products/<product id>/, the media route accepted
  bare file names only. Every uploaded image was a 404. (The generated covers
  live directly in products/, which is why the shop looked fine.)
* Metadata stripping failed OPEN: on any error the original bytes were stored,
  GPS coordinates included, while the page said "metadata stripped".
"""

import io
import os
import uuid
from decimal import Decimal

import pytest
from PIL import Image, PngImagePlugin

PW = 'TestPassword123!'


@pytest.fixture
def product(app, sample_vendor):
    from app import db
    from app.models.product import Product, ProductCategory

    cat = ProductCategory(id=uuid.uuid4(), name=f'img{uuid.uuid4().hex[:6]}',
                          slug=f'img{uuid.uuid4().hex[:6]}')
    db.session.add(cat)
    db.session.flush()
    item = Product(id=uuid.uuid4(), vendor_id=sample_vendor.id, category_id=cat.id,
                   title='photo item', description='d' * 12, price=Decimal('5'), quantity=5,
                   is_active=True, is_approved=True)
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def vendor_client(app, sample_vendor):
    client = app.test_client()
    client.post('/auth/login', data={'username': sample_vendor.username, 'password': PW})
    return client


def jpeg_with_gps():
    img = Image.new('RGB', (40, 30), (200, 10, 10))
    exif = Image.Exif()
    exif[0x010F] = 'SpyCam Inc.'                       # Make
    exif[0x8825] = {2: (52.0, 31.0, 12.0), 1: 'N'}     # GPSInfo
    buf = io.BytesIO()
    img.save(buf, format='JPEG', exif=exif)
    return buf.getvalue()


def png_with_text_and_icc():
    img = Image.new('RGBA', (20, 20), (0, 200, 0, 128))
    info = PngImagePlugin.PngInfo()
    info.add_text('Author', 'Jane Doe, 12 Secret Street')
    buf = io.BytesIO()
    img.save(buf, format='PNG', pnginfo=info, icc_profile=b'fake-icc-profile-bytes')
    return buf.getvalue()


def palette_png():
    img = Image.new('P', (10, 10))
    img.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def upload(client, product, data, name):
    return client.post(f'/vendor/product/{product.id}/upload-image',
                       data={'image': (io.BytesIO(data), name)},
                       content_type='multipart/form-data')


def stored_image(app, product):
    from app import db
    from app.models.product import ProductImage

    db.session.expire_all()
    return ProductImage.query.filter_by(product_id=product.id).first()


def fetch_primary(app, client, product):
    from app import db
    from app.models.product import Product

    db.session.expire_all()
    with app.test_request_context():
        url = db.session.get(Product, product.id).primary_image_url
    response = client.get(url)
    data = response.get_data()
    response.close()
    return response.status_code, data


class TestUploadedImagesAreServed:
    def test_uploaded_image_is_reachable_through_the_shop_url(self, app, vendor_client, product):
        upload(vendor_client, product, jpeg_with_gps(), 'holiday.jpg')

        status, data = fetch_primary(app, vendor_client, product)

        assert status == 200
        assert Image.open(io.BytesIO(data)).size == (40, 30)

    @pytest.mark.parametrize('path', [
        'not-a-uuid/file.jpg',
        f'{uuid.uuid4()}/../../etc/passwd',
        f'{uuid.uuid4()}/{uuid.uuid4()}/file.jpg',
    ])
    def test_only_one_product_directory_is_accepted(self, client, path):
        assert client.get(f'/media/products/{path}').status_code in (404, 308)


class TestMetadataIsRemoved:
    def test_gps_and_camera_are_gone_from_jpeg(self, app, vendor_client, product):
        upload(vendor_client, product, jpeg_with_gps(), 'holiday.jpg')

        _, data = fetch_primary(app, vendor_client, product)
        exif = Image.open(io.BytesIO(data)).getexif()

        assert 0x8825 not in exif and 0x010F not in exif

    def test_png_text_and_icc_profile_are_gone(self, app, vendor_client, product):
        """Re-saving the same object kept the ICC profile: Pillow copies it from img.info."""
        upload(vendor_client, product, png_with_text_and_icc(), 'sticker.png')

        _, data = fetch_primary(app, vendor_client, product)
        info = Image.open(io.BytesIO(data)).info

        assert 'Author' not in info
        assert 'icc_profile' not in info

    def test_extension_and_mime_follow_the_format_written(self, app, vendor_client, product):
        """A palette PNG was re-encoded as JPEG but kept '.png' and was recorded as image/jpeg."""
        upload(vendor_client, product, palette_png(), 'icon.png')

        image = stored_image(app, product)
        _, data = fetch_primary(app, vendor_client, product)

        assert image.filename.endswith('.png')
        assert image.mime_type == 'image/png'
        assert Image.open(io.BytesIO(data)).format == 'PNG'


class TestFailsClosed:
    def test_unprocessable_image_is_refused_not_stored_as_is(self, app, vendor_client, product,
                                                            monkeypatch):
        """On a processing error the ORIGINAL bytes -- GPS included -- used to be stored."""
        def broken(*args, **kwargs):
            raise OSError('decoder broke')
        monkeypatch.setattr(Image, 'frombytes', broken)

        upload(vendor_client, product, jpeg_with_gps(), 'holiday.jpg')

        assert stored_image(app, product) is None
        folder = os.path.join(app.config['UPLOAD_FOLDER'], 'products', str(product.id))
        assert not os.path.isdir(folder) or os.listdir(folder) == []


class TestDeletion:
    def test_deleting_removes_the_file(self, app, vendor_client, product):
        upload(vendor_client, product, jpeg_with_gps(), 'holiday.jpg')
        image = stored_image(app, product)
        path = os.path.join(app.config['UPLOAD_FOLDER'], image.filepath)
        assert os.path.exists(path)

        vendor_client.post(f'/vendor/product/{product.id}/delete-image/{image.id}')

        assert not os.path.exists(path)
        folder = os.path.dirname(path)
        assert not os.path.isdir(os.path.join(folder, 'thumbnails')), 'no orphaned thumbnails'
