"""RegistrarBusqueda use case: FAMILIAR flow."""

from uuid import uuid4

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.domain.privacy import MenoresPrivacy
from app.personas.repositories.persona import PersonaRepository
from app.schemas import Candidato, PageMeta, ResultadoBusqueda
from app.shared._exceptions import PersonaValidationError, RostroNoDetectadoError
from app.shared._helpers import (
    ProcessedPhotos,
    _embedding_consulta,
    _gen_codigo,
    construir_meta,
    normaliza_paginacion,
)


class RegistrarBusqueda:
    """FAMILIAR flow: register a missing-person search and return top matches."""

    def __init__(self, repo: PersonaRepository, policy: MatchingPolicy):
        self._repo = repo
        self._policy = policy

    def execute(
        self,
        *,
        procesadas: ProcessedPhotos,
        nombre: str | None,
        apellido: str | None,
        edad: str | None,
        doc_tipo: str | None,
        doc_numero: str | None,
        telefono_contacto: str | None,
        limite: int,
        offset: int = 0,
        page: int | None = None,
    ) -> ResultadoBusqueda:
        """Register a missing-person search and return ranked candidates.

        Args:
            procesadas: List of processed photos with embeddings (from _procesar_fotos).
            nombre: Person's first name (optional, but required if doc_numero absent).
            apellido: Person's last name.
            edad: Age as string.
            doc_tipo: Document type (e.g., "V").
            doc_numero: Document number (required if nombre absent).
            telefono_contacto: Contact phone for reunification.
            limite: Maximum candidates to return (clamped to 1–50).

        Returns:
            ResultadoBusqueda with codigo, total, and coincidencias.

        Raises:
            RostroNoDetectadoError: If no faces detected in any photo.
            PersonaValidationError: If neither nombre nor doc_numero provided.
        """
        # Validation
        if not procesadas:
            raise RostroNoDetectadoError("No se detectó ningún rostro en la(s) foto(s).")
        if not (doc_numero or (nombre and nombre.strip())):
            raise PersonaValidationError("Indica al menos el nombre o el número de identificación.")

        limite, offset = normaliza_paginacion(limite, offset, page)

        # Build domain object
        person_id = uuid4()
        codigo = _gen_codigo()

        persona = PersonaBase(
            person_id=person_id,
            estado=Estado.BUSCADA,
            es_menor=False,
            nombre=nombre,
            apellido=apellido,
            edad=edad,
            doc_tipo=doc_tipo,
            doc_numero=doc_numero,
            telefono_contacto=telefono_contacto,
            moderacion="aprobada",
            codigo=codigo,
        )

        # Persist
        self._repo.add(person_id, persona, procesadas)

        # Search (paginado) + total real del universo de encontrados visibles
        embedding = _embedding_consulta(procesadas)
        encontrados = self._repo.search_by_estado(embedding, "encontrada", limite, offset)
        total = self._repo.count_aprobadas("encontrada")

        # Apply privacy and build response
        candidatos = [MenoresPrivacy(Candidato(**d)) for d in encontrados]
        return ResultadoBusqueda(
            codigo=codigo,
            total=len(candidatos),
            coincidencias=candidatos,
            meta=PageMeta(**construir_meta(total, limite, offset)),
        )
