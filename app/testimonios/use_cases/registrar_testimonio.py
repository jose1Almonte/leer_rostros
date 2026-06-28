"""RegistrarTestimonio use case: public flow for uploading a testimonial photo/video."""

import os
import uuid
from uuid import UUID

from app import storage
from app.shared._exceptions import (
    ArchivoInvalidoError,
    PersonaNotFoundError,
    PersonaValidationError,
)
from app.testimonios.repositories.testimonio import TestimonioRepository

FOTO_MIMES = {"image/jpeg", "image/png", "image/webp"}
VIDEO_MIMES = {"video/mp4", "video/webm"}
MIMES_PERMITIDOS = FOTO_MIMES | VIDEO_MIMES
MAX_BYTES = 50 * 1024 * 1024  # 50 MB

EXT_MAP = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/webm": "webm",
}


class RegistrarTestimonio:
    """Public flow: upload a testimonial photo/video, optionally linked to a person."""

    def __init__(self, repo: TestimonioRepository):
        self._repo = repo

    def execute(
        self,
        *,
        archivo_data: bytes,
        content_type: str,
        person_id: str | None = None,
        mensaje: str | None = None,
        nombre_testigo: str | None = None,
        contacto_testigo: str | None = None,
    ) -> dict:
        if not archivo_data:
            raise ArchivoInvalidoError("No se recibió ningún archivo.")

        if len(archivo_data) > MAX_BYTES:
            raise ArchivoInvalidoError(
                "El archivo supera el límite de 50 MB."
            )

        mime_lower = (content_type or "").lower()
        if mime_lower not in MIMES_PERMITIDOS:
            raise ArchivoInvalidoError(
                "Formato no soportado. Permitidos: JPEG, PNG, WebP (fotos) "
                "y MP4, WebM (videos)."
            )

        pid: UUID | None = None
        if person_id:
            person_id = person_id.strip()
            if not person_id:
                raise PersonaValidationError("person_id inválido.")
            try:
                pid = UUID(person_id)
            except (ValueError, AttributeError):
                raise PersonaValidationError("person_id inválido.")
            if not self._repo.persona_exists(pid):
                raise PersonaNotFoundError(
                    "No existe la persona a la que intentas asociar el testimonio."
                )
        else:
            if not (nombre_testigo and nombre_testigo.strip()):
                raise PersonaValidationError(
                    "Debes indicar tu nombre o un person_id para asociar el testimonio."
                )
            if not (contacto_testigo and contacto_testigo.strip()):
                raise PersonaValidationError(
                    "Debes indicar un medio de contacto o un person_id "
                    "para que podamos validar el testimonio."
                )

        tipo = "foto" if mime_lower in FOTO_MIMES else "video"
        ext = EXT_MAP.get(mime_lower, "bin")
        foto_id = uuid.uuid4()
        key = f"testimonios/{foto_id}.{ext}"
        url = storage.upload_file(archivo_data, key, mime_lower)

        return self._repo.add(
            person_id=pid,
            tipo=tipo,
            archivo_url=url,
            archivo_key=key,
            mime=mime_lower,
            bytes=len(archivo_data),
            mensaje=(mensaje or "").strip() or None,
            nombre_testigo=(nombre_testigo or "").strip() or None,
            contacto_testigo=(contacto_testigo or "").strip() or None,
        )
