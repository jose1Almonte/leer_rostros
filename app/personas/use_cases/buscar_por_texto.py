"""BuscarPorTexto: búsqueda autónoma por datos (sin imagen, no registra nada)."""

from app.domain.privacy import MenoresPrivacy
from app.personas.repositories.persona import PersonaRepository
from app.schemas import CandidatoTexto, PageMeta, ResultadoBusquedaTexto
from app.shared._exceptions import PersonaValidationError
from app.shared._helpers import construir_meta, normaliza_paginacion

_ESTADOS_VALIDOS = ("buscada", "encontrada")


class BuscarPorTexto:
    """Busca personas por TEXTO (cédula/nombre/apellido), sin registrar nada.

    `estado` elige el lado: 'encontrada' (default, lo que busca un familiar),
    'buscada' (búsqueda inversa de un rescatista) o None para ambos lados.
    """

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(
        self,
        *,
        nombre: str | None = None,
        apellido: str | None = None,
        doc_numero: str | None = None,
        estado: str | None = "encontrada",
        limite: int = 10,
        offset: int = 0,
        page: int | None = None,
    ) -> ResultadoBusquedaTexto:
        if not any(
            (v and v.strip()) for v in (nombre, apellido, doc_numero)
        ):
            raise PersonaValidationError(
                "Indica al menos un dato para buscar: nombre, apellido o cédula."
            )
        estado_norm = estado if estado in _ESTADOS_VALIDOS else None

        limite, offset = normaliza_paginacion(limite, offset, page)
        resultados = self._repo.buscar_por_texto(
            estado=estado_norm,
            nombre=nombre,
            apellido=apellido,
            doc_numero=doc_numero,
            limite=limite,
            offset=offset,
        )
        total = self._repo.count_por_texto(
            estado=estado_norm, nombre=nombre, apellido=apellido, doc_numero=doc_numero
        )
        candidatos = [MenoresPrivacy(CandidatoTexto(**d)) for d in resultados]
        return ResultadoBusquedaTexto(
            total=len(candidatos),
            coincidencias=candidatos,
            meta=PageMeta(**construir_meta(total, limite, offset)),
        )
