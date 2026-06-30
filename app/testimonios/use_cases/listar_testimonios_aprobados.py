"""ListarTestimoniosAprobados use case: public listing of all approved testimonials."""

from app.testimonios.repositories.testimonio import TestimonioRepository


class ListarTestimoniosAprobados:
    """Public flow: list all approved testimonials, regardless of person_id."""

    def __init__(self, repo: TestimonioRepository):
        self._repo = repo

    def execute(self, limite: int = 50) -> list[dict]:
        limite = max(1, min(limite, 200))
        return self._repo.list_all_aprobados(limite)
