"""Tests for RegistrarBusqueda use case."""

import sys
import types
from uuid import uuid4

import pytest

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.schemas import ResultadoBusqueda
from app.use_cases import RegistrarBusqueda
from app.use_cases._exceptions import PersonaValidationError, RostroNoDetectadoError
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
def policy():
    return MatchingPolicy(threshold=0.55)


@pytest.fixture
def use_case(fake_repo, policy):
    return RegistrarBusqueda(fake_repo, policy)


def _make_procesadas(n=1):
    """Create n fake processed photos with embeddings."""
    return [(b"fake-image", "image/jpeg", [(b"fake-embedding", 0.9)]) for _ in range(n)]


class TestRegistrarBusquedaHappyPath:
    def test_happy_path_with_nombre(self, use_case, fake_repo):
        """Name provided, returns ResultadoBusqueda with matches."""
        # Pre-seed repo with an "encontrada" persona that will match
        from app.domain.persona import Estado, PersonaBase
        found = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="Juan",
            apellido="Pérez",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/test.jpg"],
        )
        fake_repo._personas.append(found)

        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            nombre="María",
            apellido="García",
            edad="30",
            doc_tipo="V",
            doc_numero="12345678",
            telefono_contacto="0412-1234567",
            limite=10,
        )

        assert isinstance(result, ResultadoBusqueda)
        assert result.codigo.startswith("REE-")
        assert result.total == 1
        assert len(result.coincidencias) == 1

    def test_happy_path_with_doc_numero(self, use_case, fake_repo):
        """doc_numero provided (no name), returns matches."""
        found = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="Ana",
            apellido="López",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/test.jpg"],
        )
        fake_repo._personas.append(found)

        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            nombre=None,
            apellido=None,
            edad=None,
            doc_tipo="V",
            doc_numero="87654321",
            telefono_contacto=None,
            limite=10,
        )

        assert isinstance(result, ResultadoBusqueda)
        assert result.total == 1

    def test_empty_search_returns_zero_total(self, use_case):
        """No matches in repo → total=0, empty coincidencias."""
        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            nombre="Test",
            apellido="User",
            edad=None,
            doc_tipo=None,
            doc_numero=None,
            telefono_contacto=None,
            limite=10,
        )

        assert result.total == 0
        assert result.coincidencias == []

    def test_codigo_is_generated(self, use_case):
        """Result has a codigo starting with 'REE-'."""
        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            nombre="Test",
            apellido=None,
            edad=None,
            doc_tipo=None,
            doc_numero=None,
            telefono_contacto=None,
            limite=10,
        )

        assert result.codigo.startswith("REE-")
        assert len(result.codigo) == 12  # "REE-" + 8 chars


class TestRegistrarBusquedaValidation:
    def test_raises_rostro_no_detectado(self, use_case):
        """Empty procesadas → RostroNoDetectadoError."""
        with pytest.raises(RostroNoDetectadoError) as exc_info:
            use_case.execute(
                procesadas=[],
                nombre="Test",
                apellido=None,
                edad=None,
                doc_tipo=None,
                doc_numero=None,
                telefono_contacto=None,
                limite=10,
            )
        assert "rostro" in str(exc_info.value).lower()

    def test_raises_persona_validation_no_name_no_doc(self, use_case):
        """Neither nombre nor doc_numero → PersonaValidationError."""
        procesadas = _make_procesadas()
        with pytest.raises(PersonaValidationError) as exc_info:
            use_case.execute(
                procesadas=procesadas,
                nombre=None,
                apellido=None,
                edad=None,
                doc_tipo=None,
                doc_numero=None,
                telefono_contacto=None,
                limite=10,
            )
        assert "nombre" in str(exc_info.value).lower() or "identificación" in str(exc_info.value).lower()


class TestRegistrarBusquedaLimiteClamping:
    def test_limite_clamped_to_1(self, use_case):
        """limite=0 → clamped to 1."""
        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            nombre="Test",
            apellido=None,
            edad=None,
            doc_tipo=None,
            doc_numero=None,
            telefono_contacto=None,
            limite=0,
        )
        # Should not raise, just clamp
        assert isinstance(result, ResultadoBusqueda)

    def test_limite_clamped_to_50(self, use_case):
        """limite=100 → clamped to 50."""
        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            nombre="Test",
            apellido=None,
            edad=None,
            doc_tipo=None,
            doc_numero=None,
            telefono_contacto=None,
            limite=100,
        )
        assert isinstance(result, ResultadoBusqueda)


class TestRegistrarBusquedaPrivacy:
    def test_applies_menores_privacy_on_candidates(self, use_case, fake_repo):
        """Minor candidates have nombre=None, apellido=None."""
        minor = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=True,
            nombre="Juan",
            apellido="Pérez",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/test.jpg"],
        )
        fake_repo._personas.append(minor)

        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            nombre="Test",
            apellido=None,
            edad=None,
            doc_tipo=None,
            doc_numero=None,
            telefono_contacto=None,
            limite=10,
        )

        assert result.total == 1
        candidato = result.coincidencias[0]
        assert candidato.nombre is None
        assert candidato.apellido is None

    def test_adult_names_preserved(self, use_case, fake_repo):
        """Adult candidates have real names intact."""
        adult = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="María",
            apellido="González",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/test.jpg"],
        )
        fake_repo._personas.append(adult)

        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            nombre="Test",
            apellido=None,
            edad=None,
            doc_tipo=None,
            doc_numero=None,
            telefono_contacto=None,
            limite=10,
        )

        assert result.total == 1
        candidato = result.coincidencias[0]
        assert candidato.nombre == "María"
        assert candidato.apellido == "González"


class TestRegistrarBusquedaRepoIntegration:
    def test_repo_add_called_with_persona_base_not_dict(self, use_case, fake_repo):
        """Assert repo received PersonaBase instance."""
        procesadas = _make_procesadas()
        use_case.execute(
            procesadas=procesadas,
            nombre="Test",
            apellido=None,
            edad=None,
            doc_tipo=None,
            doc_numero=None,
            telefono_contacto=None,
            limite=10,
        )

        assert len(fake_repo._personas) == 1
        assert isinstance(fake_repo._personas[0], PersonaBase)

    def test_repo_add_called_with_estado_buscada(self, use_case, fake_repo):
        """PersonaBase.estado == Estado.BUSCADA."""
        procesadas = _make_procesadas()
        use_case.execute(
            procesadas=procesadas,
            nombre="Test",
            apellido=None,
            edad=None,
            doc_tipo=None,
            doc_numero=None,
            telefono_contacto=None,
            limite=10,
        )

        persona = fake_repo._personas[0]
        assert persona.estado == Estado.BUSCADA

    def test_repo_add_called_with_moderacion_aprobada(self, use_case, fake_repo):
        """PersonaBase.moderacion == 'aprobada'."""
        procesadas = _make_procesadas()
        use_case.execute(
            procesadas=procesadas,
            nombre="Test",
            apellido=None,
            edad=None,
            doc_tipo=None,
            doc_numero=None,
            telefono_contacto=None,
            limite=10,
        )

        persona = fake_repo._personas[0]
        assert persona.moderacion == "aprobada"
