"""ListarCoincidenciasBusqueda use case: read-only pagination for a search."""

from app.domain.privacy import MenoresPrivacy
from app.personas.repositories.persona import PersonaRepository
from app.schemas import Candidato, PageMeta, ResultadoBusqueda
from app.shared._exceptions import PersonaNotFoundError, PersonaValidationError
from app.shared._helpers import construir_meta, normaliza_paginacion


class ListarCoincidenciasBusqueda:
    """Return more match pages for an existing FAMILIAR search without re-registering it."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(
        self,
        *,
        codigo: str,
        limite: int,
        offset: int = 0,
        page: int | None = None,
    ) -> ResultadoBusqueda:
        """List paginated matches for an already registered search code."""
        if not codigo.strip():
            raise PersonaValidationError("Indica el codigo de la busqueda.")

        limite, offset = normaliza_paginacion(limite, offset, page)
        embedding = self._repo.get_busqueda_embedding(codigo.strip())
        if embedding is None:
            raise PersonaNotFoundError("No existe esa busqueda.")

        total = self._repo.count_aprobadas("encontrada")
        encontrados = self._repo.search_by_estado(
            embedding, "encontrada", limite, offset=offset
        )
        candidatos = [MenoresPrivacy(Candidato(**d)) for d in encontrados]
        return ResultadoBusqueda(
            codigo=codigo.strip(),
            total=len(candidatos),
            coincidencias=candidatos,
            data=candidatos,
            meta=PageMeta(**construir_meta(total, limite, offset)),
        )
