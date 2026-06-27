"""Tests for EliminarPersona use case."""

import sys
import types
from uuid import uuid4

import pytest

from app.domain.persona import Estado, PersonaBase
from app.use_cases import EliminarPersona
from app.use_cases._exceptions import PersonaNotFoundError
from tests.repositories.fake import FakePersonaRepository


@pytest.fixture(autouse=True)
def _mock_faces_module(monkeypatch):
    """Mock app.faces to avoid InsightFace loading in tests."""
    if "app.faces" not in sys.modules:
        mock_faces = types.ModuleType("app.faces")
        monkeypatch.setitem(sys.modules, "app.faces", mock_faces)
    faces_mod = sys.modules["app.faces"]
    monkeypatch.setattr(faces_mod, "distance_to_confidence", lambda d: 50.0)


@pytest.fixture
def fake_repo():
    return FakePersonaRepository()


@pytest.fixture
def use_case(fake_repo):
    return EliminarPersona(fake_repo)


class TestEliminarPersonaHappyPath:
    def test_happy_path_deletes_persona(self, use_case, fake_repo):
        """Valid person_id → dict with fotos count."""
        persona = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="Test",
            apellido="User",
            moderacion="aprobada",
            photos=[
                "https://fake-cdn.example.com/personas/test1.jpg",
                "https://fake-cdn.example.com/personas/test2.jpg",
            ],
        )
        fake_repo._personas.append(persona)

        result = use_case.execute(person_id=str(persona.person_id))

        assert result["person_id"] == str(persona.person_id)
        assert result["eliminada"]
        assert result["fotos"] == 1  # fake_repo.delete returns count of personas deleted

    def test_persona_removed_from_fake(self, use_case, fake_repo):
        """After delete, persona no longer in repo."""
        persona = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="Test",
            apellido="User",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/test.jpg"],
        )
        fake_repo._personas.append(persona)

        assert len(fake_repo._personas) == 1
        use_case.execute(person_id=str(persona.person_id))
        assert len(fake_repo._personas) == 0


class TestEliminarPersonaValidation:
    def test_raises_persona_not_found(self, use_case):
        """Non-existent person_id → PersonaNotFoundError."""
        with pytest.raises(PersonaNotFoundError) as exc_info:
            use_case.execute(person_id="non-existent-id")
        assert "no existe" in str(exc_info.value).lower()

    def test_exception_has_message(self, use_case):
        """Error message matches expected string."""
        with pytest.raises(PersonaNotFoundError) as exc_info:
            use_case.execute(person_id="non-existent-id")
        assert "No existe esa persona" in str(exc_info.value)
