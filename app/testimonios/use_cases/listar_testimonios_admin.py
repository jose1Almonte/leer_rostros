"""ListarTestimoniosAdmin use case: admin view of all testimonials."""

from app.testimonios.repositories.testimonio import TestimonioRepository


class ListarTestimoniosAdmin:
    """Admin flow: list all testimonials, optionally filtered by estado."""

    def __init__(self, repo: TestimonioRepository):
        self._repo = repo

    def execute(self, estado: str | None = None, limite: int = 100) -> list[dict]:
        limite = max(1, min(200, limite))
        return self._repo.list_admin(estado=estado, limite=limite)
