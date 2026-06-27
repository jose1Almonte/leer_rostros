"""ModerarPersona use case: ADMIN moderation flow."""

from app.repositories.persona import PersonaRepository
from app.use_cases._exceptions import ModificacionInvalidaError, PersonaNotFoundError


VALID_MODERACION = ("aprobada", "rechazada", "pendiente")


class ModerarPersona:
    """ADMIN flow: update moderation status for a persona."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(self, *, person_id: str, valor: str) -> dict:
        """Update moderation status for all rows with the given person_id.

        Args:
            person_id: UUID string of the persona to moderate.
            valor: New moderation value ("aprobada", "rechazada", or "pendiente").

        Returns:
            Dict with person_id, moderacion, and fotos_actualizadas count.

        Raises:
            ModificacionInvalidaError: If valor is not a valid moderation value.
            PersonaNotFoundError: If person_id does not exist.
        """
        if valor not in VALID_MODERACION:
            raise ModificacionInvalidaError(
                "valor debe ser 'aprobada', 'rechazada' o 'pendiente'"
            )

        n = self._repo.set_moderacion(person_id, valor)
        if not n:
            raise PersonaNotFoundError("No existe esa persona")

        return {
            "person_id": person_id,
            "moderacion": valor,
            "fotos_actualizadas": n,
        }
