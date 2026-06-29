"""ListarReportesAdmin use case: ADMIN list flow for reports."""

from app.reportes.repositories.reporte import ReporteRepository
from app.schemas import PageMeta, PaginaReportes, ReporteAdmin
from app.shared._helpers import construir_meta, normaliza_paginacion


class ListarReportesAdmin:
    """ADMIN flow: list received reports with optional filters and pagination."""

    def __init__(self, repo: ReporteRepository):
        self._repo = repo

    def execute(
        self,
        *,
        tipo: str | None,
        estado: str | None,
        limite: int = 100,
        offset: int = 0,
        page: int | None = None,
    ) -> PaginaReportes:
        """List reports ordered by most recent first."""
        limite, offset = normaliza_paginacion(limite, offset, page, limite_max=200)
        results = self._repo.list_admin(
            tipo=tipo,
            estado=estado,
            limite=limite,
            offset=offset,
        )
        total = self._repo.count_admin(tipo=tipo, estado=estado)
        data = [ReporteAdmin(**d) for d in results]
        return PaginaReportes(
            data=data,
            meta=PageMeta(**construir_meta(total, limite, offset)),
        )
