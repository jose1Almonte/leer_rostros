"""In-memory fake implementation of ReporteRepository for use case unit tests.

This fake implements the same public interface as ReporteRepository but stores
reports in Python lists. It is fully deterministic and configurable for testing.

IMPORTANT: This is test-only infrastructure. Do NOT import from app/ code.
"""

import uuid
from datetime import datetime
from uuid import UUID


VALID_TIPOS = ("falla", "publicacion")
VALID_ESTADOS = ("pendiente", "revisado", "resuelto", "descartado")


class FakeReporteRepository:
    """In-memory fake of ReporteRepository.

    Stores both `falla` and `publicacion` reports in a single list. Supports:
    - add_falla(): appends a falla report and returns a ReporteCreado-shaped dict
    - add_publicacion(): appends a publicacion report
    - persona_exists(): checks the personas dict for any matching person_id
    - list_admin(): filters by tipo/estado and returns ReporteAdmin-shaped dicts
    - set_estado(): updates the status of one report

    Mirrors the production repository: invalid `tipo`/`estado` values are
    silently ignored (no filter applied) — same as the original SQL behavior
    in the legacy endpoint, where only known values triggered a WHERE clause.
    """

    def __init__(self, personas: dict[UUID, bool] | None = None):
        """Optionally seed a `personas` registry for persona_exists() checks.

        Args:
            personas: Mapping of person_id (UUID) → True to indicate they exist.
                Used to simulate `personas` table content without a real DB.
        """
        self._reportes: list[dict] = []
        self._personas: dict[UUID, bool] = personas or {}

    def register_persona(self, person_id: UUID) -> None:
        """Test helper: register a persona as 'exists'."""
        self._personas[person_id] = True

    def add_falla(
        self,
        *,
        descripcion: str,
        url: str | None,
        contacto: str | None,
    ) -> dict:
        """Append a falla report and return a ReporteCreado-shaped dict."""
        rid = uuid.uuid4()
        report = {
            "id": rid,
            "tipo": "falla",
            "descripcion": descripcion,
            "person_id": None,
            "url": url,
            "contacto": contacto,
            "estado": "pendiente",
            "created_at": datetime.now(),
        }
        self._reportes.append(report)
        return {
            "id": str(rid),
            "tipo": "falla",
            "estado": "pendiente",
            "created_at": report["created_at"],
        }

    def add_publicacion(
        self,
        *,
        descripcion: str,
        person_id: UUID,
        contacto: str | None,
    ) -> dict:
        """Append a publicacion report and return a ReporteCreado-shaped dict.

        The caller MUST have verified `persona_exists(person_id)` first.
        """
        rid = uuid.uuid4()
        report = {
            "id": rid,
            "tipo": "publicacion",
            "descripcion": descripcion,
            "person_id": person_id,
            "url": None,
            "contacto": contacto,
            "estado": "pendiente",
            "created_at": datetime.now(),
        }
        self._reportes.append(report)
        return {
            "id": str(rid),
            "tipo": "publicacion",
            "estado": "pendiente",
            "created_at": report["created_at"],
        }

    def persona_exists(self, person_id: UUID) -> bool:
        """Return True if the persona was registered via register_persona()."""
        return self._personas.get(person_id, False)

    def list_admin(
        self,
        *,
        tipo: str | None = None,
        estado: str | None = None,
        limite: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Return reports as ReporteAdmin-shaped dicts, filtered + ordered by
        most recent first. Unknown tipo/estado values are ignored (no filter).
        """
        results: list[dict] = []
        for r in reversed(self._reportes):
            if tipo in VALID_TIPOS and r["tipo"] != tipo:
                continue
            if estado in VALID_ESTADOS and r["estado"] != estado:
                continue
            results.append(self._to_admin_dict(r))
        off = max(0, offset)
        return results[off: off + limite]

    def count_admin(
        self,
        *,
        tipo: str | None = None,
        estado: str | None = None,
    ) -> int:
        """Count reports using the same filters as list_admin."""
        return len(
            [
                r
                for r in self._reportes
                if (tipo not in VALID_TIPOS or r["tipo"] == tipo)
                and (estado not in VALID_ESTADOS or r["estado"] == estado)
            ]
        )

    def set_estado(self, reporte_id: UUID, estado: str) -> int:
        """Update estado for the report with the given id. Returns 1 on hit, 0 on miss."""
        for i, r in enumerate(self._reportes):
            if r["id"] == reporte_id:
                self._reportes[i] = {**r, "estado": estado}
                return 1
        return 0

    @staticmethod
    def _to_admin_dict(r: dict) -> dict:
        """Convert an internal report dict into a ReporteAdmin-shaped dict."""
        return {
            "id": str(r["id"]),
            "tipo": r["tipo"],
            "descripcion": r["descripcion"],
            "estado": r["estado"],
            "person_id": str(r["person_id"]) if r["person_id"] else None,
            "url": r["url"],
            "contacto": r["contacto"],
            "created_at": r["created_at"],
            # Publication snapshot — fake has no personas, so all None.
            "pub_nombre": None,
            "pub_estado": None,
            "pub_image_url": None,
            "pub_moderacion": None,
        }
