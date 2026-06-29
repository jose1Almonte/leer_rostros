"""Tests for BuscarAdmin use case."""

import sys
import types
from uuid import uuid4

import pytest

from app.domain.persona import Estado, PersonaBase
from app.personas.use_cases import BuscarAdmin
from app.schemas import Candidato, PaginaCandidatos
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


@pytest.fixture
def fake_repo():
    return FakePersonaRepository()


@pytest.fixture
def use_case(fake_repo):
    return BuscarAdmin(fake_repo)


def _seed(fake_repo, n, estado=Estado.ENCONTRADA, moderacion="aprobada"):
    for i in range(n):
        fake_repo._personas.append(
            PersonaBase(
                person_id=uuid4(),
                estado=estado,
                es_menor=False,
                nombre=f"P{i}",
                apellido="Test",
                moderacion=moderacion,
                photos=[f"https://fake-cdn.example.com/personas/{i}.jpg"],
            )
        )


class TestBuscarAdminHappyPath:
    def test_happy_path_returns_paginated_candidates(self, use_case, fake_repo):
        _seed(fake_repo, 3)

        page = use_case.execute(embedding=b"fake-embedding", estado=None, limite=10)

        assert isinstance(page, PaginaCandidatos)
        assert len(page.data) == 3
        assert all(isinstance(r, Candidato) for r in page.data)
        assert page.meta.total_records == 3
        assert page.meta.current_page == 1
        assert page.meta.total_pages == 1

    def test_filters_by_estado(self, use_case, fake_repo):
        _seed(fake_repo, 1, estado=Estado.BUSCADA)
        _seed(fake_repo, 1, estado=Estado.ENCONTRADA)

        page = use_case.execute(embedding=b"fake", estado="buscada", limite=10)

        assert len(page.data) == 1
        assert page.data[0].estado == "buscada"
        assert page.meta.total_records == 1

    def test_applies_menores_privacy(self, use_case, fake_repo):
        minor = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=True,
            nombre="Pedrito",
            apellido="Lopez",
            moderacion="aprobada",
            photos=["https://fake-cdn.example.com/personas/minor.jpg"],
        )
        fake_repo._personas.append(minor)

        page = use_case.execute(embedding=b"fake", estado=None, limite=10)

        assert len(page.data) == 1
        assert page.data[0].nombre == "Pedrito"
        assert page.data[0].apellido == "Lopez"

    def test_no_moderacion_filter(self, use_case, fake_repo):
        _seed(fake_repo, 1, moderacion="aprobada")
        _seed(fake_repo, 1, moderacion="pendiente")

        page = use_case.execute(embedding=b"fake", estado=None, limite=10)

        # Admin search does not filter by moderacion.
        assert len(page.data) == 2
        assert page.meta.total_records == 2

    def test_pagination_offset(self, use_case, fake_repo):
        _seed(fake_repo, 5)

        page = use_case.execute(embedding=b"fake", estado=None, limite=2, offset=2)

        assert len(page.data) == 2
        assert page.data[0].nombre == "P2"
        assert page.meta.total_records == 5
        assert page.meta.current_page == 2
        assert page.meta.total_pages == 3

    def test_page_equivale_a_offset(self, use_case, fake_repo):
        _seed(fake_repo, 5)

        por_page = use_case.execute(embedding=b"fake", estado=None, limite=2, page=2)
        por_offset = use_case.execute(embedding=b"fake", estado=None, limite=2, offset=2)

        assert [r.person_id for r in por_page.data] == [
            r.person_id for r in por_offset.data
        ]
        assert por_page.meta.current_page == 2


class TestBuscarAdminLimiteClamping:
    def test_limite_clamped(self, use_case, fake_repo):
        _seed(fake_repo, 60)

        page_0 = use_case.execute(embedding=b"fake", estado=None, limite=0)
        assert len(page_0.data) == 1
        assert page_0.meta.limit == 1

        page_100 = use_case.execute(embedding=b"fake", estado=None, limite=100)
        assert len(page_100.data) == 50
        assert page_100.meta.limit == 50
