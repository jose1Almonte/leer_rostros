"""Tests for ListarTestimoniosAdmin use case."""

from uuid import uuid4

import pytest

import app.schemas as schemas
from app.testimonios.use_cases import ListarTestimoniosAdmin
from tests.testimonios.use_cases.fake import FakeTestimonioRepository


@pytest.fixture
def fake_repo():
    return FakeTestimonioRepository()


@pytest.fixture
def use_case(fake_repo):
    return ListarTestimoniosAdmin(fake_repo)


def _seed(fake_repo, estado="pendiente", created_at="2024-01-01T00:00:00+00:00"):
    fake_repo._existing_person_ids.add(str(uuid4()))
    fake_repo._testimonios.append(
        {
            "id": str(uuid4()),
            "person_id": str(uuid4()),
            "tipo": "foto",
            "archivo_url": "https://fake-cdn.example.com/t.jpg",
            "archivo_key": "testimonios/t.jpg",
            "mime": "image/jpeg",
            "bytes": 100,
            "mensaje": "Test",
            "nombre_testigo": "Test",
            "contacto_testigo": "0412-1111111",
            "estado": estado,
            "created_at": created_at,
        }
    )


class TestListarTestimoniosAdmin:
    def test_returns_all_when_no_filter(self, use_case, fake_repo):
        _seed(fake_repo, "aprobada")
        _seed(fake_repo, "pendiente")
        _seed(fake_repo, "rechazada")

        page = use_case.execute()

        assert isinstance(page, schemas.PaginaTestimonios)
        assert len(page.data) == 3
        assert all(isinstance(t, schemas.TestimonioAdmin) for t in page.data)
        assert page.meta.total_records == 3
        assert page.meta.current_page == 1

    def test_filters_by_pendiente(self, use_case, fake_repo):
        _seed(fake_repo, "aprobada")
        _seed(fake_repo, "pendiente")

        page = use_case.execute(estado="pendiente")

        assert len(page.data) == 1
        assert page.data[0].estado == "pendiente"
        assert page.meta.total_records == 1

    def test_filters_by_aprobada(self, use_case, fake_repo):
        _seed(fake_repo, "aprobada")
        _seed(fake_repo, "pendiente")

        page = use_case.execute(estado="aprobada")

        assert len(page.data) == 1
        assert page.data[0].estado == "aprobada"
        assert page.meta.total_records == 1

    def test_filters_by_rechazada(self, use_case, fake_repo):
        _seed(fake_repo, "rechazada")
        _seed(fake_repo, "pendiente")

        page = use_case.execute(estado="rechazada")

        assert len(page.data) == 1
        assert page.data[0].estado == "rechazada"
        assert page.meta.total_records == 1

    def test_limite_respected(self, use_case, fake_repo):
        for _ in range(5):
            _seed(fake_repo, "pendiente")

        page = use_case.execute(limite=3)

        assert len(page.data) == 3
        assert page.meta.total_records == 5

    def test_pagination_offset(self, use_case, fake_repo):
        for i in range(5):
            _seed(
                fake_repo,
                "pendiente",
                created_at=f"2024-01-0{i + 1}T00:00:00+00:00",
            )

        page = use_case.execute(limite=2, offset=2)

        assert len(page.data) == 2
        assert page.meta.total_records == 5
        assert page.meta.current_page == 2
        assert page.meta.total_pages == 3

    def test_page_equivale_a_offset(self, use_case, fake_repo):
        for i in range(5):
            _seed(
                fake_repo,
                "pendiente",
                created_at=f"2024-01-0{i + 1}T00:00:00+00:00",
            )

        por_page = use_case.execute(limite=2, page=2)
        por_offset = use_case.execute(limite=2, offset=2)

        assert [t.id for t in por_page.data] == [t.id for t in por_offset.data]
        assert por_page.meta.current_page == 2

    def test_limite_clamped(self, use_case, fake_repo):
        page = use_case.execute(limite=999)
        assert page.data == []
        assert page.meta.limit == 200
