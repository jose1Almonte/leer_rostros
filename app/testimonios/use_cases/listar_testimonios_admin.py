"""ListarTestimoniosAdmin use case: admin view of all testimonials."""

from app.schemas import PageMeta, PaginaTestimonios, TestimonioAdmin
from app.shared._helpers import construir_meta, normaliza_paginacion
from app.testimonios.repositories.testimonio import TestimonioRepository


class ListarTestimoniosAdmin:
    """Admin flow: list testimonials with optional filters and pagination."""

    def __init__(self, repo: TestimonioRepository):
        self._repo = repo

    def execute(
        self,
        estado: str | None = None,
        limite: int = 100,
        offset: int = 0,
        page: int | None = None,
    ) -> PaginaTestimonios:
        limite, offset = normaliza_paginacion(limite, offset, page, limite_max=200)
        results = self._repo.list_admin(estado=estado, limite=limite, offset=offset)
        total = self._repo.count_admin(estado=estado)
        data = [TestimonioAdmin(**d) for d in results]
        return PaginaTestimonios(
            data=data,
            meta=PageMeta(**construir_meta(total, limite, offset)),
        )
