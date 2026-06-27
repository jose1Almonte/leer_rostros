"""Tests for BuscarAdmin use case."""

import sys
import types
from uuid import uuid4

import pytest

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.schemas import Candidato
from app.use_cases import BuscarAdmin
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
    return BuscarAdmin(fake_repo)


class TestBuscarAdminHappyPath:
    def test_happy_path_returns_candidates(self, use_case, fake_repo):
        """Valid embedding returns list of Candidato."""
        # Pre-seed with personas
        for i in range(3):
            persona = PersonaBase(
                person_id=uuid4(),
                estado=Estado.ENCONTRADA,
                es_menor=False,
                nombre=f"Persona {i}",
                apellido="Test",
                moderacion="aprobada",
                photos=[f"https://fake-cdn.example.com/personas/{i}.jpg"],
            )
            fake_repo._personas.append(persona)

        results = use_case.execute(embedding=b"fake-embedding", estado=None, limite=10)

        assert len(results) == 3
        assert all(isinstance(r, Candidato) for r in results)

    def test_filters_by_estado(self, use_case, fake_repo):
        """estado='buscada' returns only buscada."""
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

        results = use_case.execute(embedding=b"fake", estado="buscada", limite=10)

        assert len(results) == 1
        assert results[0].estado == "buscada"

    def test_applies_menores_privacy(self, use_case, fake_repo):
        """Minor candidates masked."""
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

        results = use_case.execute(embedding=b"fake", estado=None, limite=10)

        assert len(results) == 1
        assert results[0].nombre is None
        assert results[0].apellido is None

    def test_no_moderacion_filter(self, use_case, fake_repo):
        """Admin search returns all moderacion statuses."""
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

        results = use_case.execute(embedding=b"fake", estado=None, limite=10)

        # Admin search (search_admin) does NOT filter by moderacion
        assert len(results) == 2


class TestBuscarAdminLimiteClamping:
    def test_limite_clamped(self, use_case, fake_repo):
        """limite=0 → 1, limite=100 → 50."""
        # Add 60 personas
        for i in range(60):
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

        # limite=0 should clamp to 1
        results_0 = use_case.execute(embedding=b"fake", estado=None, limite=0)
        assert len(results_0) == 1

        # limite=100 should clamp to 50
        results_100 = use_case.execute(embedding=b"fake", estado=None, limite=100)
        assert len(results_100) == 50
