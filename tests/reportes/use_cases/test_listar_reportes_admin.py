"""Tests for ListarReportesAdmin use case."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.reportes.use_cases import ListarReportesAdmin
from app.schemas import PaginaReportes, ReporteAdmin
from tests.reportes.repositories.fake import FakeReporteRepository


@pytest.fixture
def fake_repo():
    return FakeReporteRepository()


@pytest.fixture
def use_case(fake_repo):
    return ListarReportesAdmin(fake_repo)


def _seed_reports(fake_repo: FakeReporteRepository) -> None:
    fake_repo.add_falla(descripcion="bug A", url=None, contacto=None)
    fake_repo.add_falla(descripcion="bug B", url=None, contacto=None)
    fake_repo.add_publicacion(
        descripcion="foto fea",
        person_id=uuid4(),
        contacto=None,
    )


class TestListarReportesAdminHappyPath:
    def test_returns_paginated_reportes(self, use_case, fake_repo):
        _seed_reports(fake_repo)
        page = use_case.execute(tipo=None, estado=None, limite=100)

        assert isinstance(page, PaginaReportes)
        assert len(page.data) == 3
        assert all(isinstance(r, ReporteAdmin) for r in page.data)
        assert page.meta.total_records == 3
        assert page.meta.current_page == 1
        assert page.meta.total_pages == 1

    def test_empty_repo_returns_empty_page(self, use_case):
        page = use_case.execute(tipo=None, estado=None, limite=100)
        assert page.data == []
        assert page.meta.total_records == 0
        assert page.meta.total_pages == 0

    def test_most_recent_first(self, use_case, fake_repo):
        fake_repo.add_falla(descripcion="primero", url=None, contacto=None)
        fake_repo._reportes[-1]["created_at"] = datetime.now() - timedelta(hours=2)
        fake_repo.add_falla(descripcion="segundo", url=None, contacto=None)
        fake_repo._reportes[-1]["created_at"] = datetime.now() - timedelta(hours=1)
        fake_repo.add_falla(descripcion="tercero", url=None, contacto=None)
        fake_repo._reportes[-1]["created_at"] = datetime.now()

        page = use_case.execute(tipo=None, estado=None, limite=100)

        assert [r.descripcion for r in page.data] == [
            "tercero",
            "segundo",
            "primero",
        ]

    def test_pagination_offset(self, use_case, fake_repo):
        for i in range(5):
            fake_repo.add_falla(descripcion=f"bug {i}", url=None, contacto=None)

        page = use_case.execute(tipo=None, estado=None, limite=2, offset=2)

        assert len(page.data) == 2
        assert page.meta.total_records == 5
        assert page.meta.current_page == 2
        assert page.meta.total_pages == 3

    def test_page_equivale_a_offset(self, use_case, fake_repo):
        for i in range(5):
            fake_repo.add_falla(descripcion=f"bug {i}", url=None, contacto=None)

        por_page = use_case.execute(tipo=None, estado=None, limite=2, page=2)
        por_offset = use_case.execute(tipo=None, estado=None, limite=2, offset=2)

        assert [r.id for r in por_page.data] == [r.id for r in por_offset.data]
        assert por_page.meta.current_page == 2


class TestListarReportesAdminFilters:
    def test_filter_by_tipo_falla(self, use_case, fake_repo):
        _seed_reports(fake_repo)
        page = use_case.execute(tipo="falla", estado=None, limite=100)

        assert len(page.data) == 2
        assert all(r.tipo == "falla" for r in page.data)
        assert page.meta.total_records == 2

    def test_filter_by_tipo_publicacion(self, use_case, fake_repo):
        _seed_reports(fake_repo)
        page = use_case.execute(tipo="publicacion", estado=None, limite=100)

        assert len(page.data) == 1
        assert page.data[0].tipo == "publicacion"
        assert page.meta.total_records == 1

    def test_filter_by_estado_pendiente(self, use_case, fake_repo):
        _seed_reports(fake_repo)
        page = use_case.execute(tipo=None, estado="pendiente", limite=100)

        assert len(page.data) == 3
        assert all(r.estado == "pendiente" for r in page.data)
        assert page.meta.total_records == 3

    def test_filter_combined(self, use_case, fake_repo):
        _seed_reports(fake_repo)
        page = use_case.execute(tipo="publicacion", estado="pendiente", limite=100)

        assert len(page.data) == 1
        assert page.data[0].tipo == "publicacion"
        assert page.data[0].estado == "pendiente"
        assert page.meta.total_records == 1

    def test_limite_caps_results(self, use_case, fake_repo):
        for _ in range(5):
            fake_repo.add_falla(descripcion="x", url=None, contacto=None)
        page = use_case.execute(tipo=None, estado=None, limite=2)

        assert len(page.data) == 2
        assert page.meta.total_records == 5

    def test_invalid_tipo_ignored(self, use_case, fake_repo):
        _seed_reports(fake_repo)
        page = use_case.execute(tipo="invalid", estado=None, limite=100)
        assert len(page.data) == 3

    def test_invalid_estado_ignored(self, use_case, fake_repo):
        _seed_reports(fake_repo)
        page = use_case.execute(tipo=None, estado="invalid", limite=100)
        assert len(page.data) == 3
