"""Tests for ModerarPersona use case."""

import sys
import types
from uuid import uuid4

import pytest

from app.domain.persona import Estado, PersonaBase
from app.use_cases import ModerarPersona
from app.use_cases._exceptions import ModificacionInvalidaError, PersonaNotFoundError
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
    return ModerarPersona(fake_repo)


class TestModerarPersonaHappyPath:
    def test_happy_path_aprobada(self, use_case, fake_repo):
        """Valid valor → dict with fotos_actualizadas."""
        persona = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="Test",
            apellido="User",
            moderacion="pendiente",
            photos=["https://fake-cdn.example.com/personas/test.jpg"],
        )
        fake_repo._personas.append(persona)

        result = use_case.execute(person_id=str(persona.person_id), valor="aprobada")

        assert result["person_id"] == str(persona.person_id)
        assert result["moderacion"] == "aprobada"
        assert result["fotos_actualizadas"] == 1

    def test_happy_path_rechazada(self, use_case, fake_repo):
        """Same for 'rechazada'."""
        persona = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="Test",
            apellido="User",
            moderacion="pendiente",
            photos=["https://fake-cdn.example.com/personas/test.jpg"],
        )
        fake_repo._personas.append(persona)

        result = use_case.execute(person_id=str(persona.person_id), valor="rechazada")

        assert result["moderacion"] == "rechazada"
        assert result["fotos_actualizadas"] == 1

    def test_happy_path_pendiente(self, use_case, fake_repo):
        """Same for 'pendiente'."""
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

        result = use_case.execute(person_id=str(persona.person_id), valor="pendiente")

        assert result["moderacion"] == "pendiente"
        assert result["fotos_actualizadas"] == 1


class TestModerarPersonaValidation:
    def test_raises_modificacion_invalida(self, use_case):
        """valor='invalido' → ModificacionInvalidaError."""
        with pytest.raises(ModificacionInvalidaError) as exc_info:
            use_case.execute(person_id="fake-id", valor="invalido")
        assert "aprobada" in str(exc_info.value).lower()

    def test_raises_persona_not_found(self, use_case):
        """Non-existent person_id → PersonaNotFoundError."""
        with pytest.raises(PersonaNotFoundError) as exc_info:
            use_case.execute(person_id="non-existent-id", valor="aprobada")
        assert "no existe" in str(exc_info.value).lower()

    def test_exception_has_message(self, use_case):
        """Error message matches expected string."""
        with pytest.raises(ModificacionInvalidaError) as exc_info:
            use_case.execute(person_id="fake-id", valor="invalido")
        assert "aprobada" in str(exc_info.value)
        assert "rechazada" in str(exc_info.value)
        assert "pendiente" in str(exc_info.value)
