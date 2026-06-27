"""Tests for ListarPersonasAdmin use case."""

import sys
import types
from datetime import datetime
from uuid import uuid4

import pytest

from app.domain.persona import Estado, PersonaBase
from app.schemas import PersonaAdmin
from app.use_cases import ListarPersonasAdmin
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
    return ListarPersonasAdmin(fake_repo)


class TestListarPersonasAdminHappyPath:
    def test_happy_path_returns_personas(self, use_case, fake_repo):
        """Returns list of PersonaAdmin."""
        # Pre-seed with personas
        for i in range(3):
            persona = PersonaBase(
                person_id=uuid4(),
                estado=Estado.ENCONTRADA,
                es_menor=False,
                nombre=f"Persona {i}",
                apellido="Test",
                moderacion="aprobada",
                codigo=f"REE-{i:08d}",
                photos=[f"https://fake-cdn.example.com/personas/{i}.jpg"],
            )
            fake_repo._personas.append(persona)

        results = use_case.execute(limite=10, estado=None, moderacion=None)

        assert len(results) == 3
        assert all(isinstance(r, PersonaAdmin) for r in results)

    def test_filters_by_estado(self, use_case, fake_repo):
        """estado filter works."""
        buscada = PersonaBase(
            person_id=uuid4(),
            estado=Estado.BUSCADA,
            es_menor=False,
            nombre="B",
            apellido="Test",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/b.jpg"],
        )
        encontrada = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="E",
            apellido="Test",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/e.jpg"],
        )
        fake_repo._personas.extend([buscada, encontrada])

        results = use_case.execute(limite=10, estado="buscada", moderacion=None)

        assert len(results) == 1
        assert results[0].estado == "buscada"

    def test_filters_by_moderacion(self, use_case, fake_repo):
        """moderacion filter works."""
        aprobada = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="A",
            apellido="Test",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/a.jpg"],
        )
        pendiente = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="P",
            apellido="Test",
            moderacion="pendiente",
            photos=["https://fake-cdn.example.com/personas/p.jpg"],
        )
        fake_repo._personas.extend([aprobada, pendiente])

        results = use_case.execute(limite=10, estado=None, moderacion="aprobada")

        assert len(results) == 1
        assert results[0].moderacion == "aprobada"

    def test_applies_menores_privacy(self, use_case, fake_repo):
        """Minor personas masked."""
        minor = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=True,
            nombre="Pedrito",
            apellido="López",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/minor.jpg"],
        )
        fake_repo._personas.append(minor)

        results = use_case.execute(limite=10, estado=None, moderacion=None)

        assert len(results) == 1
        assert results[0].nombre is None
        assert results[0].apellido is None

    def test_respects_limite(self, use_case, fake_repo):
        """Returns at most `limit` results."""
        # Add 10 personas
        for i in range(10):
            persona = PersonaBase(
                person_id=uuid4(),
                estado=Estado.ENCONTRADA,
                es_menor=False,
                nombre=f"P{i}",
                apellido="Test",
                moderacion="aprobada",
                photos=[f"https://fake-cdn.example.com/personas/{i}.jpg"],
            )
            fake_repo._personas.append(persona)

        results = use_case.execute(limite=5, estado=None, moderacion=None)

        assert len(results) == 5

    def test_empty_list_when_no_data(self, use_case):
        """Returns [] when fake repo empty."""
        results = use_case.execute(limite=10, estado=None, moderacion=None)

        assert results == []
