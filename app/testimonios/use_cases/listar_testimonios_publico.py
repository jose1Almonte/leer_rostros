"""ListarTestimoniosPublico use case: public listing of approved testimonials for a person."""

from uuid import UUID

from app.shared._exceptions import PersonaNotFoundError
from app.testimonios.repositories.testimonio import TestimonioRepository


class ListarTestimoniosPublico:
    """Public flow: list approved testimonials linked to a person."""

    def __init__(self, repo: TestimonioRepository):
        self._repo = repo

    def execute(self, person_id: str) -> list[dict]:
        person_id = (person_id or "").strip()
        if not person_id:
            raise PersonaNotFoundError("person_id inválido.")
        try:
            pid = UUID(person_id)
        except (ValueError, AttributeError):
            raise PersonaNotFoundError("person_id inválido.")

        if not self._repo.persona_exists(pid):
            raise PersonaNotFoundError("No existe esa persona.")

        return self._repo.list_by_person(pid)
