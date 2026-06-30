"""Tests for VerificarBuscada use case (flujo inverso del rescatista)."""

import sys
import types
from uuid import uuid4

import pytest

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.personas.use_cases import VerificarBuscada
from app.schemas import ResultadoVerificacion
from app.shared._exceptions import RostroNoDetectadoError
from tests.personas.repositories.fake import FakePersonaRepository


@pytest.fixture(autouse=True)
def _mock_faces(monkeypatch):
    if "app.faces" not in sys.modules:
        monkeypatch.setitem(sys.modules, "app.faces", types.ModuleType("app.faces"))
    monkeypatch.setattr(
        sys.modules["app.faces"], "distance_to_confidence", lambda d: 50.0, raising=False
    )


@pytest.fixture
def fake_repo():
    return FakePersonaRepository(MatchingPolicy(threshold=0.55))


@pytest.fixture
def use_case(fake_repo):
    return VerificarBuscada(fake_repo)


def _procesadas(n=1):
    return [(b"img", "image/jpeg", [(b"emb", 0.9)]) for _ in range(n)]


def _buscada(fake_repo, **kw):
    d = dict(
        person_id=uuid4(),
        estado=Estado.BUSCADA,
        es_menor=False,
        nombre="Madre",
        telefono_contacto="0412-1112233",
        moderacion="aprobada",
        photos=["https://fake-cdn.example.com/b.jpg"],
    )
    d.update(kw)
    p = PersonaBase(**d)
    fake_repo._personas.append(p)
    return p


class TestVerificarBuscada:
    def test_devuelve_familiares_que_buscan(self, use_case, fake_repo):
        b = _buscada(fake_repo, telefono_contacto="0412-7654321")
        result = use_case.execute(procesadas=_procesadas(), limite=10)
        assert isinstance(result, ResultadoVerificacion)
        assert result.total == 1
        assert result.buscadores[0].person_id == str(b.person_id)
        assert result.buscadores[0].telefono == "0412-7654321"
        assert result.buscadores[0].estado == "buscada"

    def test_no_incluye_encontrados(self, use_case, fake_repo):
        """El flujo inverso busca SOLO entre buscadas, no entre encontrados."""
        _buscada(fake_repo)
        fake_repo._personas.append(
            PersonaBase(
                person_id=uuid4(), estado=Estado.ENCONTRADA, es_menor=False,
                nombre="Hallado", moderacion="aprobada",
                photos=["https://fake-cdn.example.com/e.jpg"],
            )
        )
        result = use_case.execute(procesadas=_procesadas(), limite=10)
        assert result.total == 1
        assert all(b.estado == "buscada" for b in result.buscadores)

    def test_sin_buscadores_lista_vacia(self, use_case):
        result = use_case.execute(procesadas=_procesadas(), limite=10)
        assert result.total == 0
        assert result.buscadores == []

    def test_no_persiste_nada(self, use_case, fake_repo):
        """No debe crear ningún registro nuevo (solo consulta)."""
        antes = len(fake_repo._personas)
        use_case.execute(procesadas=_procesadas(), limite=10)
        assert len(fake_repo._personas) == antes

    def test_sin_rostro_422(self, use_case):
        with pytest.raises(RostroNoDetectadoError):
            use_case.execute(procesadas=[], limite=10)

    def test_meta_presente(self, use_case, fake_repo):
        _buscada(fake_repo)
        result = use_case.execute(procesadas=_procesadas(), limite=10)
        assert result.meta is not None
        assert result.meta.total_records == 1
