"""BuscarAdmin use case: ADMIN search flow."""

from typing import Any

from app.domain.privacy import MenoresPrivacy
from app.personas.repositories.persona import PersonaRepository
from app.schemas import Candidato, PageMeta, PaginaCandidatos
from app.shared._helpers import construir_meta, normaliza_paginacion


class BuscarAdmin:
    """ADMIN flow: compare a photo against the entire database."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(
        self,
        *,
        embedding: Any,
        estado: str | None,
        limite: int,
        offset: int = 0,
        page: int | None = None,
    ) -> PaginaCandidatos:
        """Search the database for matching candidates without moderation filtering."""
        limite, offset = normaliza_paginacion(limite, offset, page)
        results = self._repo.search_admin(embedding, estado, limite, offset=offset)
        total = self._repo.count_search_admin(estado)
        data = [MenoresPrivacy(Candidato(**d)) for d in results]
        return PaginaCandidatos(
            data=data,
            meta=PageMeta(**construir_meta(total, limite, offset)),
        )
