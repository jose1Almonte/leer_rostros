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
    monkeypatch.setattr(
        faces_mod, "distance_to_confidence", lambda d: 50.0, raising=False
    )


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

    def test_paginacion_offset(self, use_case, fake_repo):
        """limite + offset pagina correctamente sin solaparse."""
        for i in range(5):
            fake_repo._personas.append(
                PersonaBase(
                    person_id=uuid4(),
                    estado=Estado.ENCONTRADA,
                    es_menor=False,
                    nombre=f"P{i}",
                    moderacion="aprobada",
                    photos=[f"https://x/{i}.jpg"],
                )
            )
        pag1 = use_case.execute(limite=2, estado=None, moderacion=None, offset=0)
        pag2 = use_case.execute(limite=2, estado=None, moderacion=None, offset=2)
        assert len(pag1) == 2 and len(pag2) == 2
        ids1 = {r.person_id for r in pag1}
        ids2 = {r.person_id for r in pag2}
        assert ids1.isdisjoint(ids2)  # páginas no se solapan

    def test_stats_cuenta_real(self, fake_repo):
        """stats() devuelve conteos reales independientes de paginación."""
        for est in ("buscada", "encontrada", "encontrada"):
            fake_repo._personas.append(
                PersonaBase(
                    person_id=uuid4(),
                    estado=Estado(est),
                    es_menor=(est == "buscada"),
                    moderacion="aprobada",
                    photos=["https://x/x.jpg"],
                )
            )
        s = fake_repo.stats()
        assert s["total"] == 3
        assert s["encontradas"] == 2
        assert s["buscadas"] == 1
        assert s["menores"] == 1

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
        assert results[0].nombre == "Pedrito"   # menores ya NO se enmascaran
        assert results[0].apellido == "López"

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
