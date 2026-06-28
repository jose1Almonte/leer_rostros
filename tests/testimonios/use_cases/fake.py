"""In-memory fake implementation of TestimonioRepository for use case unit tests."""

import uuid
from datetime import datetime, timezone
from uuid import UUID


class FakeTestimonioRepository:
    """In-memory fake of TestimonioRepository.

    Stores testimonios as dicts. All methods return TestimonioCreado-shaped dicts
    matching the real repository's return format.
    """

    def __init__(self):
        self._testimonios: list[dict] = []
        self._existing_person_ids: set[str] = set()

    def add(
        self,
        *,
        person_id: UUID | None,
        tipo: str,
        archivo_url: str,
        archivo_key: str,
        mime: str,
        bytes: int,
        mensaje: str | None,
        nombre_testigo: str | None,
        contacto_testigo: str | None,
    ) -> dict:
        tid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        d = {
            "id": str(tid),
            "person_id": str(person_id) if person_id else None,
            "tipo": tipo,
            "archivo_url": archivo_url,
            "archivo_key": archivo_key,
            "mime": mime,
            "bytes": bytes,
            "mensaje": mensaje,
            "nombre_testigo": nombre_testigo,
            "contacto_testigo": contacto_testigo,
            "estado": "pendiente",
            "created_at": now,
        }
        self._testimonios.append(d)
        return {
            "id": d["id"],
            "person_id": d["person_id"],
            "tipo": d["tipo"],
            "estado": d["estado"],
            "created_at": d["created_at"],
        }

    def persona_exists(self, person_id: UUID) -> bool:
        return str(person_id) in self._existing_person_ids

    def list_by_person(self, person_id: UUID) -> list[dict]:
        pid = str(person_id)
        return [
            {
                "id": t["id"],
                "tipo": t["tipo"],
                "archivo_url": t["archivo_url"],
                "mensaje": t["mensaje"],
                "nombre_testigo": t["nombre_testigo"],
                "created_at": t["created_at"],
            }
            for t in self._testimonios
            if t["person_id"] == pid and t["estado"] == "aprobada"
        ]

    def list_admin(
        self, estado: str | None = None, limite: int = 100
    ) -> list[dict]:
        results = self._testimonios
        if estado:
            results = [t for t in results if t["estado"] == estado]
        results = sorted(results, key=lambda t: t["created_at"], reverse=True)[
            :limite
        ]
        return [
            {
                "id": t["id"],
                "person_id": t["person_id"],
                "tipo": t["tipo"],
                "archivo_url": t["archivo_url"],
                "mime": t["mime"],
                "bytes": t["bytes"],
                "mensaje": t["mensaje"],
                "nombre_testigo": t["nombre_testigo"],
                "contacto_testigo": t["contacto_testigo"],
                "estado": t["estado"],
                "created_at": t["created_at"],
                "pub_nombre": None,
                "pub_estado": None,
                "pub_image_url": None,
            }
            for t in results
        ]

    def get(self, id: UUID) -> dict | None:
        sid = str(id)
        for t in self._testimonios:
            if t["id"] == sid:
                return {
                    "id": t["id"],
                    "person_id": t["person_id"],
                    "tipo": t["tipo"],
                    "archivo_url": t["archivo_url"],
                    "archivo_key": t["archivo_key"],
                    "mime": t["mime"],
                    "bytes": t["bytes"],
                    "mensaje": t["mensaje"],
                    "nombre_testigo": t["nombre_testigo"],
                    "contacto_testigo": t["contacto_testigo"],
                    "estado": t["estado"],
                    "created_at": t["created_at"],
                }
        return None

    def set_estado(self, id: UUID, estado: str) -> int:
        sid = str(id)
        for t in self._testimonios:
            if t["id"] == sid:
                t["estado"] = estado
                return 1
        return 0

    def delete(self, id: UUID) -> dict | None:
        sid = str(id)
        for i, t in enumerate(self._testimonios):
            if t["id"] == sid:
                self._testimonios.pop(i)
                return {"archivo_key": t["archivo_key"]}
        return None

    def count_pendientes(self) -> int:
        return sum(1 for t in self._testimonios if t["estado"] == "pendiente")
