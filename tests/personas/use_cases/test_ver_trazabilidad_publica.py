"""Tests for VerTrazabilidadPublica use case (historial público, sin teléfono)."""

from uuid import uuid4

import pytest

from app.domain.persona import Estado, PersonaBase
from app.personas.use_cases import VerTrazabilidadPublica
from app.schemas import TrazaPersonaPublica
from app.shared._exceptions import PersonaNotFoundError
from tests.personas.repositories.fake import FakePersonaRepository


@pytest.fixture
def fake_repo():
    return FakePersonaRepository()


@pytest.fixture
def use_case(fake_repo):
    return VerTrazabilidadPublica(fake_repo)


def _seed(fake_repo, moderacion="aprobada"):
    p = PersonaBase(
        person_id=uuid4(),
        estado=Estado.ENCONTRADA,
        es_menor=False,
        nombre="Luis",
        refugio="Refugio A",
        moderacion=moderacion,
        photos=["https://fake-cdn.example.com/personas/x.jpg"],
    )
    fake_repo._personas.append(p)
    return p


class TestVerTrazabilidadPublica:
    def test_devuelve_eventos_sin_telefono(self, use_case, fake_repo):
        p = _seed(fake_repo)
        pid = str(p.person_id)
        fake_repo.add_historial(
            pid, ubicacion="Caracas", telefono_responsable="0414-1112233", nota="inicial"
        )
        fake_repo.add_historial(pid, ubicacion="Valencia", nota="traslado")

        result = use_case.execute(person_id=pid)

        assert isinstance(result, TrazaPersonaPublica)
        assert result.total_eventos == 2
        assert [e.ubicacion for e in result.eventos] == ["Caracas", "Valencia"]
        # El schema público NO tiene el campo teléfono.
        assert not hasattr(result.eventos[0], "telefono_responsable")

    def test_sin_eventos_lista_vacia(self, use_case, fake_repo):
        p = _seed(fake_repo)
        result = use_case.execute(person_id=str(p.person_id))
        assert result.total_eventos == 0
        assert result.eventos == []

    def test_persona_no_visible_404(self, use_case, fake_repo):
        """Una persona pendiente/oculta NO expone su historial públicamente."""
        p = _seed(fake_repo, moderacion="pendiente")
        with pytest.raises(PersonaNotFoundError):
            use_case.execute(person_id=str(p.person_id))

    def test_persona_rechazada_404(self, use_case, fake_repo):
        p = _seed(fake_repo, moderacion="rechazada")
        with pytest.raises(PersonaNotFoundError):
            use_case.execute(person_id=str(p.person_id))

    def test_persona_inexistente_404(self, use_case):
        with pytest.raises(PersonaNotFoundError):
            use_case.execute(person_id=str(uuid4()))
