"""In-memory fake implementation of PersonaRepository for use case unit tests.

This fake implements the same public interface as PersonaRepository but stores
data in Python lists. It is fully deterministic and configurable for testing.

IMPORTANT: This is test-only infrastructure. Do NOT import from app/ code.
"""

import uuid
from typing import Any
from uuid import UUID

from app.domain.matching import MatchingPolicy
from app.domain.persona import PersonaBase


class FakePersonaRepository:
    """In-memory fake of PersonaRepository.

    Supports:
    - add(): stores persona and generates fake embeddings
    - search_by_estado(): returns stored personas ranked by fake distance
    - search_admin(): same as search_by_estado, no moderation filter
    - list_admin(): returns stored personas as PersonaAdmin-shaped dicts
    - set_moderacion(): updates moderacion on stored personas
    - delete(): removes personas by person_id
    """

    def __init__(self, policy: MatchingPolicy | None = None):
        self._policy = policy or MatchingPolicy(threshold=0.55)
        self._personas: list[PersonaBase] = []
        self._embeddings: dict[str, list[bytes]] = {}  # person_id -> list of fake embeddings
        self._deleted: list[str] = []

    def add(
        self,
        person_id: UUID,
        persona: PersonaBase,
        procesadas: list[tuple[bytes, str, list[tuple[Any, float]]]],
    ) -> list[str]:
        """Store persona and generate fake image URLs."""
        persona.photos = []
        for _data, ct, _embs in procesadas:
            foto_id = uuid.uuid4()
            ext = ct.split('/')[-1] if '/' in ct else 'jpg'
            url = f"https://fake-cdn.example.com/personas/{foto_id}.{ext}"
            persona.photos.append(url)
        self._personas.append(persona)
        return persona.photos

    def search_by_estado(
        self, embedding: Any, estado: str | None, limit: int
    ) -> list[dict]:
        """Return stored personas filtered by estado, with fake distances.

        Simulates a cosine-distance search by assigning ascending distances
        to stored personas (0.10, 0.20, 0.30, ...) so that policy.is_match
        can be tested predictably.
        """
        candidates = [
            p for p in self._personas
            if p.moderacion == "aprobada" and (estado is None or p.estado.value == estado)
        ]
        results = []
        for i, persona in enumerate(candidates[:limit]):
            distancia = round(0.10 * (i + 1), 4)
            results.append(self._to_candidato_dict(persona, distancia))
        return results

    def search_admin(
        self, embedding: Any, estado: str | None, limit: int
    ) -> list[dict]:
        """Same as search_by_estado but no moderacion filter."""
        candidates = [
            p for p in self._personas
            if estado is None or p.estado.value == estado
        ]
        results = []
        for i, persona in enumerate(candidates[:limit]):
            distancia = round(0.10 * (i + 1), 4)
            results.append(self._to_candidato_dict(persona, distancia))
        return results

    def list_admin(
        self, limit: int, estado: str | None = None, moderacion: str | None = None
    ) -> list[dict]:
        """Return stored personas as PersonaAdmin-shaped dicts."""
        results = []
        for persona in self._personas:
            if estado and persona.estado.value != estado:
                continue
            if moderacion and persona.moderacion != moderacion:
                continue
            results.append(self._to_admin_dict(persona))
            if len(results) >= limit:
                break
        return results

    def set_moderacion(self, person_id: str, valor: str) -> int:
        """Update moderacion for all personas with the given person_id."""
        count = 0
        for i, persona in enumerate(self._personas):
            if str(persona.person_id) == person_id:
                # PersonaBase is a Pydantic BaseModel, use model_copy
                updated = persona.model_copy(update={"moderacion": valor})
                self._personas[i] = updated
                count += 1
        return count

    def delete(self, person_id: str) -> int:
        """Delete personas by person_id. Returns number of photos deleted."""
        original_count = len(self._personas)
        self._personas = [
            p for p in self._personas if str(p.person_id) != person_id
        ]
        deleted_count = original_count - len(self._personas)
        if deleted_count > 0:
            self._deleted.append(person_id)
        return deleted_count

    # -- Internal helpers --

    def _to_candidato_dict(self, persona: PersonaBase, distancia: float) -> dict:
        """Convert PersonaBase to a Candidato-shaped dict."""
        return {
            "person_id": str(persona.person_id),
            "estado": persona.estado.value,
            "es_menor": persona.es_menor,
            "nombre": persona.nombre,
            "apellido": persona.apellido,
            "edad": persona.edad,
            "refugio": persona.refugio,
            "ubicacion": persona.ubicacion or persona.refugio,
            "telefono": persona.telefono_responsable or persona.telefono_contacto,
            "descripcion": persona.descripcion,
            "image_url": persona.photos[0] if persona.photos else "",
            "distancia": distancia,
            "coincidencia": self._policy.match_percentage(distancia),
            "confianza": self._policy.confidence_band(distancia),
        }

    def _to_admin_dict(self, persona: PersonaBase) -> dict:
        """Convert PersonaBase to a PersonaAdmin-shaped dict."""
        return {
            "person_id": str(persona.person_id),
            "estado": persona.estado.value,
            "es_menor": persona.es_menor,
            "nombre": persona.nombre,
            "apellido": persona.apellido,
            "edad": persona.edad,
            "doc": persona.doc_numero,
            "refugio": persona.refugio,
            "ubicacion": persona.ubicacion,
            "telefono": persona.telefono_responsable or persona.telefono_contacto,
            "codigo": persona.codigo,
            "moderacion": persona.moderacion,
            "fotos": persona.photos,
            "created_at": None,  # Not tracked in fake
        }
