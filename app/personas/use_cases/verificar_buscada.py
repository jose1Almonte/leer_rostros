"""VerificarBuscada use case: flujo INVERSO del rescatista (sin registrar)."""

from app.domain.privacy import MenoresPrivacy
from app.personas.repositories.persona import PersonaRepository
from app.schemas import Candidato, PageMeta, ResultadoVerificacion
from app.shared._exceptions import RostroNoDetectadoError
from app.shared._helpers import (
    ProcessedPhotos,
    _embedding_consulta,
    construir_meta,
    normaliza_paginacion,
)


class VerificarBuscada:
    """Dada la foto de una persona hallada, devuelve los FAMILIARES que la buscan.

    Es el espejo de `RegistrarBusqueda`: busca entre las búsquedas activas (`buscada`)
    en vez de entre los encontrados. **No persiste nada** — es solo una consulta para
    que el rescatista verifique si alguien ya estaba buscando a esa persona.
    """

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(
        self,
        *,
        procesadas: ProcessedPhotos,
        limite: int,
        offset: int = 0,
        page: int | None = None,
    ) -> ResultadoVerificacion:
        """Busca familiares (buscada visibles) que coincidan con la foto.

        Raises:
            RostroNoDetectadoError: si no se detecta rostro en la(s) foto(s) (HTTP 422).
        """
        if not procesadas:
            raise RostroNoDetectadoError("No se detectó ningún rostro en la(s) foto(s).")

        limite, offset = normaliza_paginacion(limite, offset, page)
        embedding = _embedding_consulta(procesadas)
        buscadores = self._repo.search_by_estado(embedding, "buscada", limite, offset)
        total = self._repo.count_aprobadas("buscada")

        candidatos = [MenoresPrivacy(Candidato(**d)) for d in buscadores]
        return ResultadoVerificacion(
            total=len(candidatos),
            buscadores=candidatos,
            meta=PageMeta(**construir_meta(total, limite, offset)),
        )
