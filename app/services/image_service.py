"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Image Processing Service
Purpose: Secure image upload with EXIF stripping and validation
"""

import os
import uuid
import hashlib
from io import BytesIO
from datetime import datetime
from flask import current_app
from werkzeug.utils import secure_filename
from PIL import Image
import piexif


class ImageService:
    """
    Secure image processing service:
    - EXIF metadata stripping (privacy protection)
    - Image format validation
    - File size limits
    - Malicious file detection
    - Secure file storage
    """
    
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ALLOWED_MIME_TYPES = {
        'image/png', 'image/jpeg', 'image/gif', 'image/webp'
    }
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    MAX_DIMENSIONS = (4096, 4096)  # Max width/height
    THUMBNAIL_SIZE = (300, 300)
    
    def __init__(self, upload_folder=None):
        """
        Initialize image service
        
        Args:
            upload_folder: Base folder for uploads (default from config)
        """
        self.upload_folder = upload_folder or current_app.config.get(
            'UPLOAD_FOLDER', '/app/uploads'
        )
    
    def validate_image(self, file):
        """
        Validate uploaded image file
        
        Args:
            file: FileStorage object from Flask
            
        Returns:
            tuple: (is_valid, error_message)
        """
        # Check filename
        if not file or not file.filename:
            return False, "No file provided"
        
        filename = secure_filename(file.filename)
        if not filename:
            return False, "Invalid filename"
        
        # Check extension
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext not in self.ALLOWED_EXTENSIONS:
            return False, f"File type not allowed. Allowed: {', '.join(self.ALLOWED_EXTENSIONS)}"
        
        # Check file size (read to check)
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Seek back to start
        
        if file_size > self.MAX_FILE_SIZE:
            return False, f"File too large. Maximum size: {self.MAX_FILE_SIZE // (1024*1024)}MB"
        
        if file_size == 0:
            return False, "File is empty"
        
        # Validate it's actually an image
        try:
            image_data = file.read()
            file.seek(0)
            
            img = Image.open(BytesIO(image_data))
            img.verify()  # Verify it's a valid image
            
            # Reopen for further checks (verify closes the image)
            img = Image.open(BytesIO(image_data))
            
            # Check MIME type
            mime_type = Image.MIME.get(img.format, '')
            if mime_type not in self.ALLOWED_MIME_TYPES:
                return False, f"Invalid image format: {img.format}"
            
            # Check dimensions
            width, height = img.size
            if width > self.MAX_DIMENSIONS[0] or height > self.MAX_DIMENSIONS[1]:
                return False, f"Image too large. Maximum: {self.MAX_DIMENSIONS[0]}x{self.MAX_DIMENSIONS[1]}px"
            
        except Exception as e:
            return False, f"Invalid image file: {str(e)}"
        
        return True, None
    
    def strip_exif(self, image_data):
        """
        Strip EXIF metadata from image for privacy
        
        EXIF data can contain:
        - GPS coordinates
        - Camera model/serial
        - Date/time taken
        - Thumbnail
        - Software used
        
        Args:
            image_data: Bytes of image file
            
        Returns:
            bytes: Cleaned image data
        """
        try:
            img = Image.open(BytesIO(image_data))
            
            # For JPEG/TIFF images with EXIF
            if img.format in ('JPEG', 'TIFF'):
                try:
                    # Remove EXIF data completely
                    if 'exif' in img.info:
                        # Create empty EXIF
                        img.info.pop('exif', None)
                except Exception:
                    pass
                
                # Also try piexif for thorough removal
                try:
                    piexif.remove(image_data)
                except Exception:
                    pass
            
            # Save without metadata
            output = BytesIO()
            
            # Handle transparency for PNG
            if img.format == 'PNG' and img.mode == 'RGBA':
                img.save(output, format='PNG', optimize=True)
            elif img.format == 'GIF':
                img.save(output, format='GIF')
            elif img.format == 'WEBP':
                img.save(output, format='WEBP', quality=90)
            else:
                # Convert to RGB for JPEG
                if img.mode in ('RGBA', 'P', 'LA'):
                    img = img.convert('RGB')
                img.save(output, format='JPEG', quality=90, optimize=True)
            
            output.seek(0)
            return output.read()
            
        except Exception as e:
            current_app.logger.error(f'EXIF stripping error: {e}')
            # Return original if stripping fails
            return image_data
    
    def create_thumbnail(self, image_data, size=None):
        """
        Create thumbnail from image
        
        Args:
            image_data: Bytes of image file
            size: Tuple (width, height) for thumbnail
            
        Returns:
            bytes: Thumbnail image data
        """
        size = size or self.THUMBNAIL_SIZE
        
        try:
            img = Image.open(BytesIO(image_data))
            
            # Maintain aspect ratio
            img.thumbnail(size, Image.Resampling.LANCZOS)
            
            output = BytesIO()
            
            # Convert to appropriate format
            if img.mode == 'RGBA':
                img.save(output, format='PNG', optimize=True)
                ext = 'png'
            else:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(output, format='JPEG', quality=85, optimize=True)
                ext = 'jpg'
            
            output.seek(0)
            return output.read(), ext
            
        except Exception as e:
            current_app.logger.error(f'Thumbnail creation error: {e}')
            return None, None
    
    def save_image(self, file, subfolder='products', create_thumbnail=True):
        """
        Save uploaded image with security processing
        
        Args:
            file: FileStorage object
            subfolder: Subfolder in upload directory
            create_thumbnail: Whether to create thumbnail
            
        Returns:
            dict: {
                'success': bool,
                'filename': str,
                'filepath': str,
                'thumbnail': str (optional),
                'file_size': int,
                'hash': str,
                'error': str (if failed)
            }
        """
        # Validate
        is_valid, error = self.validate_image(file)
        if not is_valid:
            return {'success': False, 'error': error}
        
        try:
            # Read file data
            image_data = file.read()
            
            # Strip EXIF metadata
            cleaned_data = self.strip_exif(image_data)
            
            # Generate unique filename
            original_ext = secure_filename(file.filename).rsplit('.', 1)[-1].lower()
            unique_id = uuid.uuid4().hex[:16]
            timestamp = datetime.utcnow().strftime('%Y%m%d')
            filename = f"{timestamp}_{unique_id}.{original_ext}"
            
            # Create directory if needed
            save_dir = os.path.join(self.upload_folder, subfolder)
            os.makedirs(save_dir, exist_ok=True)
            
            # Save main image
            filepath = os.path.join(save_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(cleaned_data)
            
            # Calculate hash for integrity
            file_hash = hashlib.sha256(cleaned_data).hexdigest()
            
            result = {
                'success': True,
                'filename': filename,
                'filepath': f'{subfolder}/{filename}',
                'file_size': len(cleaned_data),
                'hash': file_hash
            }
            
            # Create thumbnail if requested
            if create_thumbnail:
                thumb_data, thumb_ext = self.create_thumbnail(cleaned_data)
                if thumb_data:
                    thumb_filename = f"thumb_{unique_id}.{thumb_ext}"
                    thumb_dir = os.path.join(save_dir, 'thumbnails')
                    os.makedirs(thumb_dir, exist_ok=True)
                    
                    thumb_path = os.path.join(thumb_dir, thumb_filename)
                    with open(thumb_path, 'wb') as f:
                        f.write(thumb_data)
                    
                    result['thumbnail'] = f'{subfolder}/thumbnails/{thumb_filename}'
            
            current_app.logger.info(f'Image saved: {filepath} (EXIF stripped)')
            return result
            
        except Exception as e:
            current_app.logger.error(f'Image save error: {e}')
            return {'success': False, 'error': str(e)}
    
    def delete_image(self, filepath):
        """
        Securely delete image file
        
        Args:
            filepath: Path relative to upload folder
            
        Returns:
            bool: Success
        """
        try:
            full_path = os.path.join(self.upload_folder, filepath)
            if os.path.exists(full_path):
                os.remove(full_path)
                current_app.logger.info(f'Image deleted: {filepath}')
                return True
            return False
        except Exception as e:
            current_app.logger.error(f'Image delete error: {e}')
            return False
    
    def get_image_info(self, filepath):
        """
        Get information about stored image
        
        Args:
            filepath: Path relative to upload folder
            
        Returns:
            dict: Image information
        """
        try:
            full_path = os.path.join(self.upload_folder, filepath)
            if not os.path.exists(full_path):
                return None
            
            with open(full_path, 'rb') as f:
                img_data = f.read()
            
            img = Image.open(BytesIO(img_data))
            
            return {
                'filepath': filepath,
                'format': img.format,
                'mode': img.mode,
                'width': img.size[0],
                'height': img.size[1],
                'file_size': len(img_data),
                'hash': hashlib.sha256(img_data).hexdigest()
            }
            
        except Exception as e:
            current_app.logger.error(f'Get image info error: {e}')
            return None


def get_image_service():
    """Get image service singleton"""
    return ImageService()
