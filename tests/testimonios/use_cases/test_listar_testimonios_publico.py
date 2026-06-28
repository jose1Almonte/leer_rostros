"""Tests for ListarTestimoniosPublico use case."""

from uuid import uuid4

import pytest

from app.testimonios.use_cases import ListarTestimoniosPublico
from app.shared._exceptions import PersonaNotFoundError
from tests.testimonios.use_cases.fake import FakeTestimonioRepository


@pytest.fixture
def fake_repo():
    return FakeTestimonioRepository()


@pytest.fixture
def use_case(fake_repo):
    return ListarTestimoniosPublico(fake_repo)


class TestListarTestimoniosPublico:
    def test_returns_only_approved(self, use_case, fake_repo):
        """Only testimonios with estado='aprobada' are returned."""
        pid = uuid4()
        fake_repo._existing_person_ids.add(str(pid))

        fake_repo._testimonios.append(
            {
                "id": str(uuid4()),
                "person_id": str(pid),
                "tipo": "foto",
                "archivo_url": "https://fake-cdn.example.com/1.jpg",
                "archivo_key": "testimonios/1.jpg",
                "mensaje": "Aprobado",
                "nombre_testigo": "Test",
                "contacto_testigo": "0412-1111111",
                "estado": "aprobada",
                "created_at": "2024-01-01T00:00:00+00:00",
                "mime": "image/jpeg",
                "bytes": 100,
            }
        )
        fake_repo._testimonios.append(
            {
                "id": str(uuid4()),
                "person_id": str(pid),
                "tipo": "foto",
                "archivo_url": "https://fake-cdn.example.com/2.jpg",
                "archivo_key": "testimonios/2.jpg",
                "mensaje": "Pendiente",
                "nombre_testigo": "Test",
                "contacto_testigo": None,
                "estado": "pendiente",
                "created_at": "2024-01-02T00:00:00+00:00",
                "mime": "image/jpeg",
                "bytes": 100,
            }
        )

        results = use_case.execute(person_id=str(pid))
        assert len(results) == 1
        assert results[0]["mensaje"] == "Aprobado"

    def test_raises_persona_not_found(self, use_case):
        """Non-existent person_id → PersonaNotFoundError."""
        with pytest.raises(PersonaNotFoundError):
            use_case.execute(person_id=str(uuid4()))

    def test_raises_empty_person_id(self, use_case):
        """Empty person_id → PersonaNotFoundError."""
        with pytest.raises(PersonaNotFoundError):
            use_case.execute(person_id="")

    def test_raises_invalid_uuid(self, use_case):
        """Malformed person_id → PersonaNotFoundError."""
        with pytest.raises(PersonaNotFoundError):
            use_case.execute(person_id="not-a-uuid")

    def test_empty_list_when_no_approved(self, use_case, fake_repo):
        """No approved testimonios → empty list."""
        pid = uuid4()
        fake_repo._existing_person_ids.add(str(pid))
        results = use_case.execute(person_id=str(pid))
        assert results == []
