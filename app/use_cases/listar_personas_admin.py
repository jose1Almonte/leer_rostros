"""ListarPersonasAdmin use case: ADMIN list flow."""

from app.domain.privacy import MenoresPrivacy
from app.repositories.persona import PersonaRepository
from app.schemas import PersonaAdmin


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
    ) -> list[PersonaAdmin]:
        """List personas for admin view (paginado con offset).

        Returns:
            List of PersonaAdmin with privacy masking applied.
        """
        results = self._repo.list_admin(limite, estado, moderacion, offset=offset)
        return [MenoresPrivacy(PersonaAdmin(**d)) for d in results]
