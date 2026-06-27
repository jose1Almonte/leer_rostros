"""EliminarPersona use case: ADMIN delete flow."""

from app.repositories.persona import PersonaRepository
from app.use_cases._exceptions import PersonaNotFoundError


class EliminarPersona:
    """ADMIN flow: delete a persona and its associated images."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(self, *, person_id: str) -> dict:
        """Delete a persona and all its photos.

        Args:
            person_id: UUID string of the persona to delete.

        Returns:
            Dict with person_id, eliminada=True, and fotos count.

        Raises:
            PersonaNotFoundError: If person_id does not exist.
        """
        fotos = self._repo.delete(person_id)
        if not fotos:
            raise PersonaNotFoundError("No existe esa persona")

        return {
            "person_id": person_id,
            "eliminada": True,
            "fotos": fotos,
        }
