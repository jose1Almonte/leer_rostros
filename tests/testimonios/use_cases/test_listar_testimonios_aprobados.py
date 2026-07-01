"""Tests for ListarTestimoniosAprobados use case."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.testimonios.use_cases import ListarTestimoniosAprobados
from tests.testimonios.use_cases.fake import FakeTestimonioRepository


@pytest.fixture
def fake_repo():
    return FakeTestimonioRepository()


@pytest.fixture
def use_case(fake_repo):
    return ListarTestimoniosAprobados(fake_repo)


def _seed(fake_repo, *, estado="aprobada", person_id=None, days_ago=0):
    fake_repo._testimonios.append(
        {
            "id": str(uuid4()),
            "person_id": str(person_id or uuid4()),
            "tipo": "foto",
            "archivo_url": "https://fake-cdn.example.com/t.jpg",
            "archivo_key": "testimonios/t.jpg",
            "mime": "image/jpeg",
            "bytes": 100,
            "mensaje": "Test",
            "nombre_testigo": "Test",
            "contacto_testigo": None,
            "estado": estado,
            "created_at": datetime.now(timezone.utc) - timedelta(days=days_ago),
        }
    )


class TestListarTestimoniosAprobados:
    def test_returns_only_approved(self, use_case, fake_repo):
        _seed(fake_repo, estado="aprobada")
        _seed(fake_repo, estado="pendiente")
        _seed(fake_repo, estado="rechazada")
        results = use_case.execute()
        assert len(results) == 1

    def test_returns_all_approved_regardless_of_person(self, use_case, fake_repo):
        _seed(fake_repo, estado="aprobada", person_id=uuid4())
        _seed(fake_repo, estado="aprobada", person_id=uuid4())
        _seed(fake_repo, estado="aprobada", person_id=uuid4())
        results = use_case.execute()
        assert len(results) == 3

    def test_returns_approved_with_person_id(self, use_case, fake_repo):
        pid = uuid4()
        _seed(fake_repo, estado="aprobada", person_id=pid)
        results = use_case.execute()
        assert len(results) == 1
        assert results[0]["person_id"] == str(pid)

    def test_respects_limite(self, use_case, fake_repo):
        for _ in range(5):
            _seed(fake_repo, estado="aprobada")
        results = use_case.execute(limite=3)
        assert len(results) == 3

    def test_limite_clamping(self, use_case, fake_repo):
        results = use_case.execute(limite=999)
        assert len(results) == 0

    def test_empty_list_when_no_approved(self, use_case):
        results = use_case.execute()
        assert results == []

    def test_orders_by_newest_first(self, use_case, fake_repo):
        _seed(fake_repo, estado="aprobada", days_ago=10)
        _seed(fake_repo, estado="aprobada", days_ago=1)
        _seed(fake_repo, estado="aprobada", days_ago=5)
        results = use_case.execute()
        assert len(results) == 3
        assert results[0]["created_at"] > results[1]["created_at"] > results[2]["created_at"]
