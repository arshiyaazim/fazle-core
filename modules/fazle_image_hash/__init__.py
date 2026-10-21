"""
Fazle Core — Image Hash & Duplicate Detection (Phase 4E)

Uses MD5 hash of file content to detect duplicate slip uploads.
Fast and reliable — same file always produces same hash.
phash (perceptual hash) requires Pillow+imagehash — we detect if available.
"""

import hashlib
import logging
import os
from typing import TypedDict, Optional

from app.database import fetch_one, execute

log = logging.getLogger("fazle.image_hash")

# Try to import perceptual hashing (optional)
try:
    from PIL import Image
    import imagehash
    _PHASH_AVAILABLE = True
except ImportError:
    _PHASH_AVAILABLE = False
    log.debug("imagehash/Pillow not installed — using MD5 only")


class ImageHashResult(TypedDict):
    md5: str
    phash: Optional[str]
    file_size: int
    is_duplicate: bool
    duplicate_of_message_id: Optional[int]


async def check_and_register(file_path: str, message_id: Optional[int] = None) -> ImageHashResult:
    """
    Compute hash, check DB for duplicate, optionally register if new.
    Returns result dict with is_duplicate flag.
    """
    md5 = _md5(file_path)
    phash = _phash(file_path) if _PHASH_AVAILABLE else None
    size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

    # Check duplicate by MD5
    existing = await fetch_one(
        """SELECT message_id FROM fazle_whatsapp_messages
           WHERE metadata_json->>'image_md5' = $1
           LIMIT 1""",
        md5,
    )
    is_dup = existing is not None
    dup_msg_id = existing["message_id"] if existing else None

    # Register new hash if not duplicate and message_id given
    if not is_dup and message_id:
        phash_val = phash or ""
        await execute(
            """UPDATE fazle_whatsapp_messages
               SET metadata_json = COALESCE(metadata_json, '{}') ||
                   jsonb_build_object(
                       'image_md5', $1::text,
                       'image_phash', $2::text,
                       'image_size', $3::int
                   )
               WHERE message_id = $4""",
            md5, phash_val, size, message_id,
        )

    log.info(f"[image_hash] md5={md5[:12]} phash={phash} size={size} dup={is_dup}")
    return ImageHashResult(
        md5=md5,
        phash=phash,
        file_size=size,
        is_duplicate=is_dup,
        duplicate_of_message_id=dup_msg_id,
    )


def _md5(file_path: str) -> str:
    h = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except Exception as e:
        log.warning(f"MD5 error: {e}")
    return h.hexdigest()


def _phash(file_path: str) -> Optional[str]:
    try:
        img = Image.open(file_path).convert("RGB")
        return str(imagehash.phash(img))
    except Exception as e:
        log.debug(f"phash error: {e}")
        return None


def phash_similarity(hash1: str, hash2: str) -> float:
    """Return similarity 0.0-1.0 between two phash strings (1.0 = identical)."""
    if not _PHASH_AVAILABLE or not hash1 or not hash2:
        return 1.0 if hash1 == hash2 else 0.0
    try:
        h1 = imagehash.hex_to_hash(hash1)
        h2 = imagehash.hex_to_hash(hash2)
        diff = h1 - h2  # hamming distance (0-64)
        return 1.0 - (diff / 64.0)
    except Exception:
        return 0.0
