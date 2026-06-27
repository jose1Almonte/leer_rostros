"""BuscarAdmin use case: ADMIN search flow."""

from typing import Any

from app.domain.privacy import MenoresPrivacy
from app.repositories.persona import PersonaRepository
from app.schemas import Candidato
from app.use_cases._helpers import LIMITE_MAX


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
    ) -> list[Candidato]:
        """Search the database for matching candidates (no moderation filter).

        Args:
            embedding: Query embedding vector (from faces.embedding_from_bytes).
            estado: Optional filter ("buscada" or "encontrada").
            limite: Maximum results (clamped to 1–50).

        Returns:
            List of Candidato with privacy masking applied.
        """
        limite = max(1, min(LIMITE_MAX, limite))
        results = self._repo.search_admin(embedding, estado, limite)
        return [MenoresPrivacy(Candidato(**d)) for d in results]
