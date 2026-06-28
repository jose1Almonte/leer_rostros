"""ListarPersonasAdmin use case: ADMIN list flow."""

from app.domain.privacy import MenoresPrivacy
from app.personas.repositories.persona import PersonaRepository
from app.schemas import PaginaPersonas, PageMeta, PersonaAdmin
from app.shared._helpers import construir_meta, normaliza_paginacion


class ListarPersonasAdmin:
    """ADMIN flow: list all registered personas with optional filters."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(
        self,
        *,
        limite: int,
        estado: str | None,
        moderacion: str | None,
        offset: int = 0,
        page: int | None = None,
    ) -> PaginaPersonas:
        """List personas for admin view (paginado: limit + offset/page).

        Returns:
            PaginaPersonas con `data` (PersonaAdmin con privacy aplicada) y `meta`.
        """
        limite, offset = normaliza_paginacion(limite, offset, page)
        results = self._repo.list_admin(limite, estado, moderacion, offset=offset)
        total = self._repo.count_admin(estado, moderacion)
        data = [MenoresPrivacy(PersonaAdmin(**d)) for d in results]
        return PaginaPersonas(data=data, meta=PageMeta(**construir_meta(total, limite, offset)))
