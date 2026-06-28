"""Tests for EliminarTestimonio use case."""

from uuid import uuid4

import pytest

from app.testimonios.use_cases import EliminarTestimonio
from app.shared._exceptions import TestimonioNotFoundError
from tests.testimonios.use_cases.fake import FakeTestimonioRepository


@pytest.fixture
def fake_repo():
    return FakeTestimonioRepository()


@pytest.fixture
def use_case(fake_repo):
    return EliminarTestimonio(fake_repo)


def _seed(fake_repo):
    tid = uuid4()
    fake_repo._existing_person_ids.add(str(uuid4()))
    fake_repo._testimonios.append(
        {
            "id": str(tid),
            "person_id": str(uuid4()),
            "tipo": "foto",
            "archivo_url": "https://fake-cdn.example.com/t.jpg",
            "archivo_key": "testimonios/t.jpg",
            "mime": "image/jpeg",
            "bytes": 100,
            "mensaje": "Test",
            "nombre_testigo": "Test",
            "contacto_testigo": "0412-1111111",
            "estado": "pendiente",
            "created_at": "2024-01-01T00:00:00+00:00",
        }
    )
    return str(tid)


class TestEliminarTestimonio:
    def test_elimina_con_archivo_key(self, use_case, fake_repo):
        tid = _seed(fake_repo)
        result = use_case.execute(id=tid)
        assert result["eliminado"] is True
        assert len(fake_repo._testimonios) == 0

    def test_raises_not_found(self, use_case):
        with pytest.raises(TestimonioNotFoundError):
            use_case.execute(id=str(uuid4()))

    def test_raises_empty_id(self, use_case):
        with pytest.raises(TestimonioNotFoundError):
            use_case.execute(id="")

    def test_raises_invalid_uuid(self, use_case):
        with pytest.raises(TestimonioNotFoundError):
            use_case.execute(id="not-a-uuid")
