"""VerTrazabilidadPublica use case: histórico PÚBLICO (sin teléfono)."""

from app.personas.repositories.persona import PersonaRepository
from app.schemas import EventoHistorialPublico, TrazaPersonaPublica
from app.shared._exceptions import PersonaNotFoundError


class VerTrazabilidadPublica:
    """Histórico de avistamientos para CUALQUIER persona (vista pública).

    Igual que `VerTrazabilidad` pero:
      - Solo funciona si la persona está VISIBLE (moderación aprobada); si no, 404
        (no se filtra la existencia de publicaciones ocultas/pendientes).
      - NUNCA expone el teléfono del responsable (dato sensible, solo admin).
    """

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(self, *, person_id: str) -> TrazaPersonaPublica:
        """Lista los avistamientos (sin teléfono) en orden cronológico.

        Raises:
            PersonaNotFoundError: si la persona no existe o no es visible (HTTP 404).
        """
        if not self._repo.persona_visible(person_id):
            raise PersonaNotFoundError("No existe esa persona.")

        eventos = [
            EventoHistorialPublico(
                id=e["id"],
                person_id=e["person_id"],
                refugio=e["refugio"],
                ubicacion=e["ubicacion"],
                encontrado_por=e["encontrado_por"],
                nota=e["nota"],
                created_at=e["created_at"],
            )
            for e in self._repo.list_historial(person_id)
        ]
        return TrazaPersonaPublica(
            person_id=person_id,
            total_eventos=len(eventos),
            eventos=eventos,
        )
