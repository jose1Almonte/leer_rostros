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


def normaliza_paginacion(limite: int, offset: int = 0, page: int | None = None) -> tuple[int, int]:
    """Normaliza parámetros de paginación.

    Acepta `offset` directo o `page` (1-based, tiene prioridad si se envía).
    `limite` se acota a 1..LIMITE_MAX. Devuelve (limite, offset) saneados.
    """
    limite = max(1, min(LIMITE_MAX, limite))
    if page is not None and page >= 1:
        offset = (page - 1) * limite
    return limite, max(0, offset)


def construir_meta(total: int, limite: int, offset: int) -> dict:
    """Construye el objeto `meta` de paginación a partir del total real."""
    limite = max(1, limite)
    total = max(0, total)
    return {
        "total_records": total,
        "current_page": offset // limite + 1,
        "total_pages": (total + limite - 1) // limite if total else 0,
        "limit": limite,
        "offset": offset,
    }
