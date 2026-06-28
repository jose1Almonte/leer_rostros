"""In-memory fake implementation of PersonaRepository for use case unit tests.

This fake implements the same public interface as PersonaRepository but stores
data in Python lists. It is fully deterministic and configurable for testing.

IMPORTANT: This is test-only infrastructure. Do NOT import from app/ code.
"""

import uuid
from datetime import datetime
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
        self._embeddings: dict[
            str, list[Any]
        ] = {}  # codigo -> list of fake embeddings for registered searches
        self._deleted: list[str] = []
        self._historial: list[dict] = []  # eventos de trazabilidad
        self._seq: int = 0  # contador determinista para ids/timestamps de eventos

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
            ext = ct.split("/")[-1] if "/" in ct else "jpg"
            url = f"https://fake-cdn.example.com/personas/{foto_id}.{ext}"
            persona.photos.append(url)
            if persona.codigo:
                self._embeddings.setdefault(persona.codigo, []).extend(
                    emb for emb, _calidad in _embs
                )
        self._personas.append(persona)
        return persona.photos

    def search_by_estado(
        self, embedding: Any, estado: str | None, limit: int, offset: int = 0
    ) -> list[dict]:
        """Return stored personas filtered by estado, with fake distances (paginado).

        Simulates a cosine-distance search by assigning ascending distances
        to stored personas (0.10, 0.20, 0.30, ...) so that policy.is_match
        can be tested predictably.
        """
        candidates = [
            p
            for p in self._personas
            if p.moderacion == "aprobada"
            and (estado is None or p.estado.value == estado)
        ]
        results = []
        for i, persona in enumerate(candidates):
            distancia = round(0.10 * (i + 1), 4)
            results.append(self._to_candidato_dict(persona, distancia))
        off = max(0, offset)
        return results[off: off + limit]

    def find_encontrada_by_doc(self, doc_numero: str) -> dict | None:
        """Primera persona ENCONTRADA con la misma cédula (normalizada), o None."""
        if not doc_numero or not doc_numero.strip():
            return None
        target = doc_numero.strip().casefold()
        for p in self._personas:
            if p.estado.value != "encontrada":
                continue
            if p.doc_numero and p.doc_numero.strip().casefold() == target:
                return {
                    "person_id": str(p.person_id),
                    "nombre": p.nombre,
                    "apellido": p.apellido,
                    "doc_numero": p.doc_numero,
                    "refugio": p.refugio,
                    "ubicacion": p.ubicacion,
                    "image_url": p.photos[0] if p.photos else None,
                    "es_menor": p.es_menor,
                    "codigo": p.codigo,
                }
        return None

    def persona_exists(self, person_id: str) -> bool:
        return any(str(p.person_id) == person_id for p in self._personas)

    def get_persona_basics(self, person_id: str) -> dict | None:
        for p in self._personas:
            if str(p.person_id) == person_id:
                return {
                    "person_id": person_id,
                    "doc_numero": p.doc_numero,
                    "estado": p.estado.value,
                    "nombre": p.nombre,
                    "apellido": p.apellido,
                }
        return None

    def find_buscadas_by_doc(self, doc_numero: str) -> list[dict]:
        """Búsqueda inversa: familiares (buscada visibles) con esta cédula."""
        if not doc_numero or not doc_numero.strip():
            return []
        target = doc_numero.strip().casefold()
        out = []
        seen = set()
        for p in self._personas:
            if p.estado.value != "buscada" or p.moderacion != "aprobada":
                continue
            if not p.doc_numero or p.doc_numero.strip().casefold() != target:
                continue
            if str(p.person_id) in seen:
                continue
            seen.add(str(p.person_id))
            out.append({
                "person_id": str(p.person_id),
                "nombre": p.nombre,
                "apellido": p.apellido,
                "telefono": p.telefono_contacto or p.telefono_responsable,
                "image_url": p.photos[0] if p.photos else None,
                "es_menor": p.es_menor,
            })
        return out

    def add_historial(
        self,
        person_id: str,
        *,
        refugio: str | None = None,
        ubicacion: str | None = None,
        encontrado_por: str | None = None,
        telefono_responsable: str | None = None,
        nota: str | None = None,
        actualizar_actual: bool = True,
    ) -> dict:
        self._seq += 1
        evento = {
            "id": f"evt-{self._seq}",
            "person_id": person_id,
            "refugio": refugio,
            "ubicacion": ubicacion,
            "encontrado_por": encontrado_por,
            "telefono_responsable": telefono_responsable,
            "nota": nota,
            "created_at": datetime(2026, 1, 1, 0, 0, self._seq % 60),
        }
        self._historial.append(evento)
        if actualizar_actual:
            for i, p in enumerate(self._personas):
                if str(p.person_id) != person_id:
                    continue
                upd = {}
                if refugio:
                    upd["refugio"] = refugio
                if ubicacion:
                    upd["ubicacion"] = ubicacion
                if encontrado_por:
                    upd["encontrado_por"] = encontrado_por
                if telefono_responsable:
                    upd["telefono_responsable"] = telefono_responsable
                if upd:
                    self._personas[i] = p.model_copy(update=upd)
        return dict(evento)

    def list_historial(self, person_id: str) -> list[dict]:
        return [
            dict(e) for e in self._historial if e["person_id"] == person_id
        ]

    def count_historial(self, person_id: str) -> int:
        return sum(1 for e in self._historial if e["person_id"] == person_id)

    def find_exact_match(
        self,
        *,
        doc_numero: str,
        nombre: str,
        apellido: str | None = None,
        estado: str = "encontrada",
    ) -> dict | None:
        """Match EXACTO por texto (cédula + nombre [+ apellido]) normalizado."""
        def norm(s: str | None) -> str:
            return s.strip().casefold() if s else ""

        for p in self._personas:
            if p.estado.value != estado or p.moderacion != "aprobada":
                continue
            if not p.doc_numero or norm(p.doc_numero) != norm(doc_numero):
                continue
            if not p.nombre or norm(p.nombre) != norm(nombre):
                continue
            if apellido and apellido.strip() and norm(p.apellido) != norm(apellido):
                continue
            d = self._to_candidato_dict(p, 0.0)
            d.update({"distancia": 0.0, "coincidencia": 100, "confianza": "alta"})
            return d
        return None

    def list_publico(self, estado: str, limit: int, offset: int = 0) -> list[dict]:
        """Listado público (encontradas aprobadas) con campos no sensibles."""
        filtered = [
            {
                "person_id": str(p.person_id),
                "estado": p.estado.value,
                "es_menor": p.es_menor,
                "nombre": p.nombre,
                "apellido": p.apellido,
                "edad": p.edad,
                "ubicacion": p.ubicacion or p.refugio,
                "descripcion": p.descripcion,
                "image_url": p.photos[0] if p.photos else None,
                "created_at": datetime.now(),
            }
            for p in self._personas
            if p.estado.value == estado and p.moderacion == "aprobada"
        ]
        off = max(0, offset)
        return filtered[off: off + limit]

    def count_aprobadas(self, estado: str | None = None) -> int:
        return len({
            str(p.person_id)
            for p in self._personas
            if p.moderacion == "aprobada" and (estado is None or p.estado.value == estado)
        })

    def count_admin(self, estado: str | None = None, moderacion: str | None = None) -> int:
        return len({
            str(p.person_id)
            for p in self._personas
            if (not estado or p.estado.value == estado)
            and (not moderacion or p.moderacion == moderacion)
        })

    def get_busqueda_embedding(self, codigo: str) -> Any | None:
        """Return first stored fake embedding for a search code."""
        embeddings = self._embeddings.get(codigo)
        return embeddings[0] if embeddings else None

    def search_admin(
        self, embedding: Any, estado: str | None, limit: int
    ) -> list[dict]:
        """Same as search_by_estado but no moderacion filter."""
        candidates = [
            p for p in self._personas if estado is None or p.estado.value == estado
        ]
        results = []
        for i, persona in enumerate(candidates[:limit]):
            distancia = round(0.10 * (i + 1), 4)
            results.append(self._to_candidato_dict(persona, distancia))
        return results

    def list_admin(
        self,
        limit: int,
        estado: str | None = None,
        moderacion: str | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """Return stored personas as PersonaAdmin-shaped dicts (paginado con offset)."""
        filtered = []
        for persona in self._personas:
            if estado and persona.estado.value != estado:
                continue
            if moderacion and persona.moderacion != moderacion:
                continue
            filtered.append(self._to_admin_dict(persona))
        return filtered[max(0, offset): max(0, offset) + limit]

    def stats(self) -> dict:
        """Conteos en memoria para tests del dashboard."""
        pids = {str(p.person_id) for p in self._personas}
        by = lambda pred: len({str(p.person_id) for p in self._personas if pred(p)})
        return {
            "total": len(pids),
            "buscadas": by(lambda p: p.estado.value == "buscada"),
            "encontradas": by(lambda p: p.estado.value == "encontrada"),
            "menores": by(lambda p: p.es_menor),
            "ocultas": by(lambda p: p.moderacion == "rechazada"),
            "pendientes_moderacion": by(lambda p: p.moderacion == "pendiente"),
            "reportes_publicaciones": 0,
            "reportes_publicaciones_pendientes": 0,
            "reportes_fallas": 0,
            "reportes_fallas_pendientes": 0,
        }

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
        self._personas = [p for p in self._personas if str(p.person_id) != person_id]
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
            "created_at": datetime.now(),
        }
