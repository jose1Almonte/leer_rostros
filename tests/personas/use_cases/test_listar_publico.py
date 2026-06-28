"""Tests for ListarPublico use case (directorio público, sin datos sensibles)."""

from uuid import uuid4

import pytest

from app.domain.persona import Estado, PersonaBase
from app.schemas import PaginaPublica, PersonaPublica
from app.personas.use_cases import ListarPublico
from tests.personas.repositories.fake import FakePersonaRepository


@pytest.fixture
def fake_repo():
    return FakePersonaRepository()


@pytest.fixture
def use_case(fake_repo):
    return ListarPublico(fake_repo)


def _enc(fake_repo, nombre, menor=False, moderacion="aprobada", tel="0412-1"):
    fake_repo._personas.append(
        PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=menor,
            nombre=nombre,
            apellido="X",
            telefono_responsable=tel,
            ubicacion="Refugio",
            moderacion=moderacion,
            photos=["https://x/p.jpg"],
        )
    )


class TestListarPublico:
    def test_devuelve_pagina_publica(self, use_case, fake_repo):
        _enc(fake_repo, "Ana")
        res = use_case.execute(estado="encontrada", limite=10)
        assert isinstance(res, PaginaPublica)
        assert len(res.data) == 1
        assert isinstance(res.data[0], PersonaPublica)
        assert res.meta.total_records == 1

    def test_no_expone_telefono(self, use_case, fake_repo):
        _enc(fake_repo, "Ana", tel="0412-SECRETO")
        res = use_case.execute(estado="encontrada", limite=10)
        # PersonaPublica no tiene campo telefono
        assert not hasattr(res.data[0], "telefono")
        assert "telefono" not in res.data[0].model_dump()

    def test_menores_enmascarados(self, use_case, fake_repo):
        _enc(fake_repo, "Pedrito", menor=True)
        res = use_case.execute(estado="encontrada", limite=10)
        assert res.data[0].es_menor is True
        assert res.data[0].nombre is None
        assert res.data[0].apellido is None

    def test_solo_aprobadas(self, use_case, fake_repo):
        _enc(fake_repo, "Visible", moderacion="aprobada")
        _enc(fake_repo, "Oculta", moderacion="pendiente")
        res = use_case.execute(estado="encontrada", limite=10)
        assert len(res.data) == 1
        assert res.data[0].nombre == "Visible"

    def test_paginacion(self, use_case, fake_repo):
        for i in range(5):
            _enc(fake_repo, f"P{i}")
        p1 = use_case.execute(estado="encontrada", limite=2, page=1)
        p2 = use_case.execute(estado="encontrada", limite=2, page=2)
        assert len(p1.data) == 2 and len(p2.data) == 2
        assert p1.meta.total_records == 5
        assert p1.meta.total_pages == 3
        assert {r.person_id for r in p1.data}.isdisjoint({r.person_id for r in p2.data})
