"""Tests for ListarCoincidenciasBusqueda use case."""

import sys
import types
from uuid import uuid4

import pytest

from app.domain.persona import Estado, PersonaBase
from app.personas.use_cases import ListarCoincidenciasBusqueda
from app.shared._exceptions import PersonaNotFoundError
from tests.personas.repositories.fake import FakePersonaRepository


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


def _make_procesadas():
    return [(b"fake-image", "image/jpeg", [(b"fake-embedding", 0.9)])]


@pytest.fixture
def fake_repo():
    return FakePersonaRepository()


@pytest.fixture
def use_case(fake_repo):
    return ListarCoincidenciasBusqueda(fake_repo)


def _seed_search(fake_repo, codigo="REE-TEST123"):
    search = PersonaBase(
        person_id=uuid4(),
        estado=Estado.BUSCADA,
        es_menor=False,
        nombre="Maria",
        codigo=codigo,
        moderacion="aprobada",
    )
    fake_repo.add(search.person_id, search, _make_procesadas())
    return codigo


def _seed_found(fake_repo, count=5):
    for i in range(count):
        found = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre=f"Encontrada {i}",
            moderacion="aprobada",
            photos=[f"https://fake-cdn.example.com/personas/{i}.jpg"],
        )
        fake_repo._personas.append(found)


def test_returns_paginated_matches_for_existing_search(use_case, fake_repo):
    codigo = _seed_search(fake_repo)
    _seed_found(fake_repo, count=5)

    result = use_case.execute(codigo=codigo, limite=2, offset=2)

    assert result.codigo == codigo
    assert result.total == 2
    assert result.data == result.coincidencias
    assert [c.nombre for c in result.data] == ["Encontrada 2", "Encontrada 3"]
    assert result.meta.total_records == 5
    assert result.meta.current_page == 2
    assert result.meta.total_pages == 3
    assert result.meta.limit == 2
    assert result.meta.offset == 2


def test_page_parameter_wins_over_offset(use_case, fake_repo):
    codigo = _seed_search(fake_repo)
    _seed_found(fake_repo, count=5)

    result = use_case.execute(codigo=codigo, limite=2, offset=0, page=3)

    assert [c.nombre for c in result.data] == ["Encontrada 4"]
    assert result.meta.current_page == 3
    assert result.meta.offset == 4


def test_raises_not_found_for_unknown_codigo(use_case):
    with pytest.raises(PersonaNotFoundError):
        use_case.execute(codigo="REE-MISSING", limite=10)
