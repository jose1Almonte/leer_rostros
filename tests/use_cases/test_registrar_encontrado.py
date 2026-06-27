"""Tests for RegistrarEncontrado use case."""

import sys
import types
from uuid import uuid4

import pytest

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.schemas import ResultadoRegistro
from app.use_cases import RegistrarEncontrado
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
    return RegistrarEncontrado(fake_repo, policy)


def _make_procesadas(n=1):
    """Create n fake processed photos with embeddings."""
    return [(b"fake-image", "image/jpeg", [(b"fake-embedding", 0.9)]) for _ in range(n)]


class TestRegistrarEncontradoHappyPath:
    def test_happy_path_no_match(self, use_case, fake_repo):
        """Valid registration, no cross-match, alerta=None."""
        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            es_menor=False,
            nombre="Juan",
            apellido="Pérez",
            doc_tipo="V",
            doc_numero="12345678",
            refugio="Refugio Central",
            ubicacion="Caracas",
            telefono_responsable="0414-1234567",
            doc_responsable=None,
            descripcion="Alto, moreno",
        )

        assert isinstance(result, ResultadoRegistro)
        assert result.codigo.startswith("REE-")
        assert result.alerta is None
        assert len(fake_repo._personas) == 1

    def test_happy_path_with_match(self, use_case, fake_repo):
        """Cross-match exists, alerta is populated."""
        # Pre-seed with a "buscada" persona
        buscada = PersonaBase(
            person_id=uuid4(),
            estado=Estado.BUSCADA,
            es_menor=False,
            nombre="María",
            apellido="González",
            telefono_contacto="0412-9999999",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/buscada.jpg"],
        )
        fake_repo._personas.append(buscada)

        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            es_menor=False,
            nombre="Juan",
            apellido="Pérez",
            doc_tipo="V",
            doc_numero="12345678",
            refugio="Refugio Central",
            ubicacion="Caracas",
            telefono_responsable="0414-1234567",
            doc_responsable=None,
            descripcion=None,
        )

        assert result.alerta is not None
        assert result.alerta.familiar_nombre == "María"
        assert result.alerta.familiar_telefono == "0412-9999999"

    def test_alerta_menor_masks_nombre(self, use_case, fake_repo):
        """Match is minor, alerta.familiar_nombre is None."""
        minor_buscada = PersonaBase(
            person_id=uuid4(),
            estado=Estado.BUSCADA,
            es_menor=True,
            nombre="Pedrito",
            apellido="López",
            telefono_contacto="0412-8888888",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/minor.jpg"],
        )
        fake_repo._personas.append(minor_buscada)

        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            es_menor=False,
            nombre="Test",
            apellido=None,
            doc_tipo=None,
            doc_numero=None,
            refugio="Refugio",
            ubicacion=None,
            telefono_responsable="0414-1234567",
            doc_responsable=None,
            descripcion=None,
        )

        assert result.alerta is not None
        assert result.alerta.familiar_nombre is None  # Masked

    def test_alerta_non_minor_preserves_nombre(self, use_case, fake_repo):
        """Match is adult, familiar_nombre preserved."""
        adult_buscada = PersonaBase(
            person_id=uuid4(),
            estado=Estado.BUSCADA,
            es_menor=False,
            nombre="Carlos",
            apellido="Martínez",
            telefono_contacto="0412-7777777",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/adult.jpg"],
        )
        fake_repo._personas.append(adult_buscada)

        procesadas = _make_procesadas()
        result = use_case.execute(
            procesadas=procesadas,
            es_menor=False,
            nombre="Test",
            apellido=None,
            doc_tipo=None,
            doc_numero=None,
            refugio="Refugio",
            ubicacion=None,
            telefono_responsable="0414-1234567",
            doc_responsable=None,
            descripcion=None,
        )

        assert result.alerta is not None
        assert result.alerta.familiar_nombre == "Carlos"

    def test_minor_name_stored_not_nulled(self, use_case, fake_repo):
        """Minor's nombre stored in persona, only masked in response."""
        procesadas = _make_procesadas()
        use_case.execute(
            procesadas=procesadas,
            es_menor=True,
            nombre="Pedrito",
            apellido="López",
            doc_tipo=None,
            doc_numero=None,
            refugio="Refugio",
            ubicacion=None,
            telefono_responsable="0414-1234567",
            doc_responsable="V-11111111",
            descripcion=None,
        )

        # Stored persona has the name
        stored = fake_repo._personas[0]
        assert stored.nombre == "Pedrito"
        assert stored.apellido == "López"


class TestRegistrarEncontradoValidation:
    def test_raises_rostro_no_detectado(self, use_case):
        """Empty procesadas → RostroNoDetectadoError."""
        with pytest.raises(RostroNoDetectadoError) as exc_info:
            use_case.execute(
                procesadas=[],
                es_menor=False,
                nombre="Test",
                apellido=None,
                doc_tipo=None,
                doc_numero=None,
                refugio="Refugio",
                ubicacion=None,
                telefono_responsable="0414-1234567",
                doc_responsable=None,
                descripcion=None,
            )
        assert "rostro" in str(exc_info.value).lower()

    def test_raises_persona_validation_no_refugio(self, use_case):
        """Missing refugio → PersonaValidationError."""
        procesadas = _make_procesadas()
        with pytest.raises(PersonaValidationError) as exc_info:
            use_case.execute(
                procesadas=procesadas,
                es_menor=False,
                nombre="Test",
                apellido=None,
                doc_tipo=None,
                doc_numero=None,
                refugio=None,
                ubicacion=None,
                telefono_responsable="0414-1234567",
                doc_responsable=None,
                descripcion=None,
            )
        assert "refugio" in str(exc_info.value).lower()

    def test_raises_persona_validation_no_telefono_responsable(self, use_case):
        """Missing telefono_responsable → PersonaValidationError."""
        procesadas = _make_procesadas()
        with pytest.raises(PersonaValidationError) as exc_info:
            use_case.execute(
                procesadas=procesadas,
                es_menor=False,
                nombre="Test",
                apellido=None,
                doc_tipo=None,
                doc_numero=None,
                refugio="Refugio",
                ubicacion=None,
                telefono_responsable=None,
                doc_responsable=None,
                descripcion=None,
            )
        assert "teléfono" in str(exc_info.value).lower()

    def test_raises_persona_validation_menor_sin_doc_responsable(self, use_case):
        """es_menor=True, no doc_responsable → PersonaValidationError."""
        procesadas = _make_procesadas()
        with pytest.raises(PersonaValidationError) as exc_info:
            use_case.execute(
                procesadas=procesadas,
                es_menor=True,
                nombre="Pedrito",
                apellido=None,
                doc_tipo=None,
                doc_numero=None,
                refugio="Refugio",
                ubicacion=None,
                telefono_responsable="0414-1234567",
                doc_responsable=None,
                descripcion=None,
            )
        assert "responsable" in str(exc_info.value).lower()


class TestRegistrarEncontradoRepoIntegration:
    def test_repo_add_called_with_estado_encontrada(self, use_case, fake_repo):
        """PersonaBase.estado == Estado.ENCONTRADA."""
        procesadas = _make_procesadas()
        use_case.execute(
            procesadas=procesadas,
            es_menor=False,
            nombre="Test",
            apellido=None,
            doc_tipo=None,
            doc_numero=None,
            refugio="Refugio",
            ubicacion=None,
            telefono_responsable="0414-1234567",
            doc_responsable=None,
            descripcion=None,
        )

        persona = fake_repo._personas[0]
        assert persona.estado == Estado.ENCONTRADA

    def test_repo_add_called_with_moderacion_pendiente(self, use_case, fake_repo):
        """PersonaBase.moderacion == 'pendiente'."""
        procesadas = _make_procesadas()
        use_case.execute(
            procesadas=procesadas,
            es_menor=False,
            nombre="Test",
            apellido=None,
            doc_tipo=None,
            doc_numero=None,
            refugio="Refugio",
            ubicacion=None,
            telefono_responsable="0414-1234567",
            doc_responsable=None,
            descripcion=None,
        )

        persona = fake_repo._personas[0]
        assert persona.moderacion == "pendiente"

    def test_repo_add_called_with_es_menor_true(self, use_case, fake_repo):
        """PersonaBase.es_menor matches input."""
        procesadas = _make_procesadas()
        use_case.execute(
            procesadas=procesadas,
            es_menor=True,
            nombre="Pedrito",
            apellido=None,
            doc_tipo=None,
            doc_numero=None,
            refugio="Refugio",
            ubicacion=None,
            telefono_responsable="0414-1234567",
            doc_responsable="V-11111111",
            descripcion=None,
        )

        persona = fake_repo._personas[0]
        assert persona.es_menor
