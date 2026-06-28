"""ListarPublico use case: directorio PÚBLICO paginado (sin datos sensibles)."""

from app.personas.repositories.persona import PersonaRepository
from app.schemas import PageMeta, PaginaPublica, PersonaPublica
from app.shared._helpers import construir_meta, normaliza_paginacion


class ListarPublico:
    """Listado público de personas (encontradas/buscadas) sin teléfono ni documento.

    Solo muestra publicaciones `moderacion='aprobada'`. Enmascara el nombre de los
    menores (privacidad): en una vista pública no hay % de coincidencia que justifique
    revelarlo, así que se oculta siempre para `es_menor`.
    """

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(
        self,
        *,
        estado: str,
        limite: int,
        offset: int = 0,
        page: int | None = None,
    ) -> PaginaPublica:
        limite, offset = normaliza_paginacion(limite, offset, page)
        rows = self._repo.list_publico(estado, limite, offset)
        total = self._repo.count_aprobadas(estado)
        data = []
        for d in rows:
            if d.get("es_menor"):
                d = {**d, "nombre": None, "apellido": None}
            data.append(PersonaPublica(**d))
        return PaginaPublica(data=data, meta=PageMeta(**construir_meta(total, limite, offset)))
