"""
Image Service Tests for Social Market.

Tests cover:
- EXIF metadata stripping
- Image file validation (format, size, dimensions)
- Allowed/disallowed file types
- Thumbnail creation
"""

import io
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image


def _create_test_image(format='JPEG', size=(100, 100), mode='RGB'):
    """Create a test image in memory."""
    img = Image.new(mode, size, color='red')
    buf = io.BytesIO()
    img.save(buf, format=format)
    buf.seek(0)
    return buf


def _create_file_storage(data, filename, content_type='image/jpeg'):
    """Create a werkzeug FileStorage-like object."""
    from werkzeug.datastructures import FileStorage
    return FileStorage(
        stream=data,
        filename=filename,
        content_type=content_type,
    )


class TestImageValidation:
    """Tests for image validation."""

    def test_valid_jpeg(self, app):
        """Valid JPEG should pass validation."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            img_data = _create_test_image('JPEG')
            file = _create_file_storage(img_data, 'test.jpg')
            is_valid, error = svc.validate_image(file)
            assert is_valid is True
            assert error is None

    def test_valid_png(self, app):
        """Valid PNG should pass validation."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            img_data = _create_test_image('PNG', mode='RGBA')
            file = _create_file_storage(img_data, 'test.png', 'image/png')
            is_valid, error = svc.validate_image(file)
            assert is_valid is True
            assert error is None

    def test_invalid_extension(self, app):
        """File with disallowed extension should fail."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            img_data = _create_test_image('JPEG')
            file = _create_file_storage(img_data, 'test.exe')
            is_valid, error = svc.validate_image(file)
            assert is_valid is False
            assert 'not allowed' in error

    def test_empty_file(self, app):
        """Empty file should fail validation."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            file = _create_file_storage(io.BytesIO(b''), 'empty.jpg')
            is_valid, error = svc.validate_image(file)
            assert is_valid is False

    def test_no_file(self, app):
        """None file should fail validation."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            is_valid, error = svc.validate_image(None)
            assert is_valid is False
            assert 'No file' in error

    def test_oversized_file(self, app):
        """File exceeding MAX_FILE_SIZE should fail."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            svc.MAX_FILE_SIZE = 100  # Set very small limit for testing

            img_data = _create_test_image('JPEG', size=(500, 500))
            file = _create_file_storage(img_data, 'large.jpg')
            is_valid, error = svc.validate_image(file)
            assert is_valid is False
            assert 'too large' in error.lower()

    def test_oversized_dimensions(self, app):
        """Image exceeding MAX_DIMENSIONS should fail."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            svc.MAX_DIMENSIONS = (50, 50)  # Set very small limit

            img_data = _create_test_image('JPEG', size=(100, 100))
            file = _create_file_storage(img_data, 'big_dims.jpg')
            is_valid, error = svc.validate_image(file)
            assert is_valid is False
            assert 'too large' in error.lower()

    def test_non_image_file(self, app):
        """Non-image file with image extension should fail."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            fake_data = io.BytesIO(b'This is not an image file content')
            file = _create_file_storage(fake_data, 'fake.jpg')
            is_valid, error = svc.validate_image(file)
            assert is_valid is False


class TestExifStripping:
    """Tests for EXIF metadata stripping."""

    def test_strip_exif_returns_data(self, app):
        """EXIF stripping should return valid image data."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            img_data = _create_test_image('JPEG')
            raw_data = img_data.read()
            cleaned = svc.strip_exif(raw_data)
            assert len(cleaned) > 0
            # Verify it's still a valid image
            img = Image.open(io.BytesIO(cleaned))
            assert img.size == (100, 100)

    def test_strip_exif_png(self, app):
        """EXIF stripping should work for PNG files."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            img_data = _create_test_image('PNG', mode='RGBA')
            raw_data = img_data.read()
            cleaned = svc.strip_exif(raw_data)
            assert len(cleaned) > 0
            img = Image.open(io.BytesIO(cleaned))
            assert img.format == 'PNG'


class TestThumbnailCreation:
    """Tests for thumbnail creation."""

    def test_create_thumbnail(self, app):
        """Thumbnail should be created with correct size."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            img_data = _create_test_image('JPEG', size=(800, 600))
            raw_data = img_data.read()
            thumb_data, ext = svc.create_thumbnail(raw_data, size=(200, 200))
            assert thumb_data is not None
            assert ext in ('jpg', 'png')

            # Verify thumbnail dimensions
            thumb = Image.open(io.BytesIO(thumb_data))
            assert thumb.size[0] <= 200
            assert thumb.size[1] <= 200

    def test_thumbnail_maintains_aspect_ratio(self, app):
        """Thumbnail should maintain aspect ratio."""
        with app.app_context():
            from app.services.image_service import ImageService
            svc = ImageService(upload_folder='/tmp/test_uploads')
            img_data = _create_test_image('JPEG', size=(800, 400))
            raw_data = img_data.read()
            thumb_data, ext = svc.create_thumbnail(raw_data, size=(200, 200))
            thumb = Image.open(io.BytesIO(thumb_data))
            # Width should be 200, height should be ~100 (maintaining 2:1 ratio)
            assert thumb.size[0] == 200
            assert thumb.size[1] == 100


class TestImageSaveAndDelete:
    """Tests for image save and delete operations."""

    def test_save_image_success(self, app):
        """Image save should succeed and return correct metadata."""
        import tempfile
        with app.app_context():
            from app.services.image_service import ImageService
            with tempfile.TemporaryDirectory() as tmpdir:
                svc = ImageService(upload_folder=tmpdir)
                img_data = _create_test_image('JPEG')
                file = _create_file_storage(img_data, 'product.jpg')
                result = svc.save_image(file, subfolder='test', create_thumbnail=False)
                assert result['success'] is True
                assert result['filename'].endswith('.jpg')
                assert result['file_size'] > 0
                assert 'hash' in result

    def test_delete_image(self, app):
        """Image delete should remove the file."""
        import tempfile
        import os
        with app.app_context():
            from app.services.image_service import ImageService
            with tempfile.TemporaryDirectory() as tmpdir:
                svc = ImageService(upload_folder=tmpdir)
                img_data = _create_test_image('JPEG')
                file = _create_file_storage(img_data, 'delete_me.jpg')
                result = svc.save_image(file, subfolder='test', create_thumbnail=False)
                assert result['success'] is True

                # Now delete
                deleted = svc.delete_image(result['filepath'])
                assert deleted is True
                assert not os.path.exists(os.path.join(tmpdir, result['filepath']))
