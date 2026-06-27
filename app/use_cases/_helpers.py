"""Shared helpers used across use cases."""

from typing import Any

import uuid


# Type alias for processed photos (same shape as _procesar_fotos output)
# Each tuple: (image_bytes, content_type, [(embedding_array, calidad_score), ...])
ProcessedPhotos = list[tuple[bytes, str, list[tuple[Any, float]]]]

LIMITE_MAX = 50


def _gen_codigo() -> str:
    """Generate a unique registration code (e.g., 'REE-A1B2C3D4')."""
    return "REE-" + uuid.uuid4().hex[:8].upper()


def _embedding_consulta(procesadas: ProcessedPhotos) -> Any | None:
    """Get the base embedding from the first processed photo for search queries.

    Returns the first embedding from the first photo, or None if no photos.
    """
    return procesadas[0][2][0][0] if procesadas else None
