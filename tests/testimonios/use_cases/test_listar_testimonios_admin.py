"""Tests for ListarTestimoniosAdmin use case."""

from uuid import uuid4

import pytest

from app.testimonios.use_cases import ListarTestimoniosAdmin
from tests.testimonios.use_cases.fake import FakeTestimonioRepository


@pytest.fixture
def fake_repo():
    return FakeTestimonioRepository()


@pytest.fixture
def use_case(fake_repo):
    return ListarTestimoniosAdmin(fake_repo)


def _seed(fake_repo, estado="pendiente"):
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
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    )


class TestListarTestimoniosAdmin:
    def test_returns_all_when_no_filter(self, use_case, fake_repo):
        _seed(fake_repo, "aprobada")
        _seed(fake_repo, "pendiente")
        _seed(fake_repo, "rechazada")
        results = use_case.execute()
        assert len(results) == 3

    def test_filters_by_pendiente(self, use_case, fake_repo):
        _seed(fake_repo, "aprobada")
        _seed(fake_repo, "pendiente")
        results = use_case.execute(estado="pendiente")
        assert len(results) == 1
        assert results[0]["estado"] == "pendiente"

    def test_filters_by_aprobada(self, use_case, fake_repo):
        _seed(fake_repo, "aprobada")
        _seed(fake_repo, "pendiente")
        results = use_case.execute(estado="aprobada")
        assert len(results) == 1
        assert results[0]["estado"] == "aprobada"

    def test_filters_by_rechazada(self, use_case, fake_repo):
        _seed(fake_repo, "rechazada")
        _seed(fake_repo, "pendiente")
        results = use_case.execute(estado="rechazada")
        assert len(results) == 1
        assert results[0]["estado"] == "rechazada"

    def test_limite_respected(self, use_case, fake_repo):
        for _ in range(5):
            _seed(fake_repo, "pendiente")
        results = use_case.execute(limite=3)
        assert len(results) == 3

    def test_limite_clamped(self, use_case, fake_repo):
        results = use_case.execute(limite=999)
        assert len(results) == 0  # no error, clamped to 200
