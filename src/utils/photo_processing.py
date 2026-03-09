"""
Photo processing utilities for AccessGrid Avigilon Unity Agent.

Plasec identity photos are not exposed in the observed API endpoints,
so photo sync is implemented as best-effort: if Plasec returns a photo
URL in the identity detail page, we download and forward it to AccessGrid.
"""

import base64
import hashlib
import io
import logging
from typing import Optional, Dict, Tuple

from ..constants import MAX_PHOTO_SIZE_MB, PHOTO_MAX_DIMENSIONS, PHOTO_JPEG_QUALITY

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)


def process_photo_bytes(photo_data: bytes) -> Optional[bytes]:
    """
    Resize and re-encode raw photo bytes to JPEG within AccessGrid limits.

    Returns processed JPEG bytes, or None if processing fails.
    """
    if not photo_data or not PIL_AVAILABLE:
        return None
    try:
        image = Image.open(io.BytesIO(photo_data))
        if image.mode != 'RGB':
            image = image.convert('RGB')
        if image.size[0] > PHOTO_MAX_DIMENSIONS[0] or image.size[1] > PHOTO_MAX_DIMENSIONS[1]:
            image.thumbnail(PHOTO_MAX_DIMENSIONS, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, format='JPEG', quality=PHOTO_JPEG_QUALITY, optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Photo processing failed: {e}")
        return None


def encode_photo_for_accessgrid(photo_data: bytes) -> Optional[str]:
    """Base64-encode photo bytes for the AccessGrid API."""
    if not photo_data:
        return None
    return base64.b64encode(photo_data).decode('utf-8')


def get_photo_hash(photo_data: Optional[bytes]) -> Optional[str]:
    """SHA-256 hash of raw photo bytes for change detection."""
    if not photo_data:
        return None
    if isinstance(photo_data, memoryview):
        photo_data = bytes(photo_data)
    return hashlib.sha256(photo_data).hexdigest()


def prepare_photo_for_sync(raw_photo_data: Optional[bytes]) -> Optional[Dict]:
    """
    Full photo preparation pipeline.

    Returns dict with 'photo_data' (base64), 'photo_format', 'processed_size',
    or None if no photo or processing fails.
    """
    if not raw_photo_data:
        return None

    processed = process_photo_bytes(raw_photo_data)
    if not processed:
        return None

    encoded = encode_photo_for_accessgrid(processed)
    if not encoded:
        return None

    return {
        'photo_data':     encoded,
        'photo_format':   'JPEG',
        'processed_size': len(processed),
    }


def get_photo_stats(photo_info: Optional[Dict]) -> str:
    if not photo_info:
        return "No photo"
    size = photo_info.get('processed_size', 0)
    return f"{size // 1024}KB"
