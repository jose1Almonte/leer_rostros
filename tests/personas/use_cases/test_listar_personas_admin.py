"""Tests for ListarPersonasAdmin use case (paginado: data + meta)."""

import sys
import types
from uuid import uuid4

import pytest

from app.domain.persona import Estado, PersonaBase
from app.schemas import PaginaPersonas, PersonaAdmin
from app.personas.use_cases import ListarPersonasAdmin
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
    return ListarPersonasAdmin(fake_repo)


def _seed(fake_repo, n, estado=Estado.ENCONTRADA, moderacion="aprobada", menor=False):
    for i in range(n):
        fake_repo._personas.append(
            PersonaBase(
                person_id=uuid4(),
                estado=estado,
                es_menor=menor,
                nombre=f"P{i}",
                apellido="Test",
                moderacion=moderacion,
                codigo=f"REE-{i:08d}",
                photos=[f"https://x/{i}.jpg"],
            )
        )


class TestListarPersonasAdminHappyPath:
    def test_devuelve_pagina_con_data_y_meta(self, use_case, fake_repo):
        _seed(fake_repo, 3)
        res = use_case.execute(limite=10, estado=None, moderacion=None)
        assert isinstance(res, PaginaPersonas)
        assert len(res.data) == 3
        assert all(isinstance(r, PersonaAdmin) for r in res.data)
        assert res.meta.total_records == 3
        assert res.meta.current_page == 1
        assert res.meta.total_pages == 1

    def test_paginacion_offset(self, use_case, fake_repo):
        """limite + offset pagina sin solaparse; meta refleja total real y páginas."""
        _seed(fake_repo, 5)
        pag1 = use_case.execute(limite=2, estado=None, moderacion=None, offset=0)
        pag2 = use_case.execute(limite=2, estado=None, moderacion=None, offset=2)
        assert len(pag1.data) == 2 and len(pag2.data) == 2
        assert {r.person_id for r in pag1.data}.isdisjoint({r.person_id for r in pag2.data})
        assert pag1.meta.total_records == 5
        assert pag1.meta.total_pages == 3  # ceil(5/2)
        assert pag2.meta.current_page == 2

    def test_page_equivale_a_offset(self, use_case, fake_repo):
        """page=2 con limite=2 == offset=2."""
        _seed(fake_repo, 5)
        por_page = use_case.execute(limite=2, estado=None, moderacion=None, page=2)
        por_offset = use_case.execute(limite=2, estado=None, moderacion=None, offset=2)
        assert [r.person_id for r in por_page.data] == [r.person_id for r in por_offset.data]
        assert por_page.meta.current_page == 2

    def test_stats_cuenta_real(self, fake_repo):
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
        _seed(fake_repo, 1, estado=Estado.BUSCADA)
        _seed(fake_repo, 1, estado=Estado.ENCONTRADA)
        res = use_case.execute(limite=10, estado="buscada", moderacion=None)
        assert len(res.data) == 1
        assert res.data[0].estado == "buscada"
        assert res.meta.total_records == 1

    def test_filters_by_moderacion(self, use_case, fake_repo):
        _seed(fake_repo, 1, moderacion="aprobada")
        _seed(fake_repo, 1, moderacion="pendiente")
        res = use_case.execute(limite=10, estado=None, moderacion="aprobada")
        assert len(res.data) == 1
        assert res.data[0].moderacion == "aprobada"

    def test_filters_by_nombre_apellido_cedula_and_es_menor(self, use_case, fake_repo):
        target = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=True,
            nombre="Ana",
            apellido="Gomez",
            doc_numero="12345678",
            moderacion="aprobada",
            codigo="REE-00000001",
            photos=["https://x/ana.jpg"],
        )
        other = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=False,
            nombre="Luis",
            apellido="Perez",
            doc_numero="87654321",
            moderacion="aprobada",
            codigo="REE-00000002",
            photos=["https://x/luis.jpg"],
        )
        fake_repo._personas.extend([target, other])

        res = use_case.execute(
            limite=10,
            estado=None,
            moderacion=None,
            nombre="an",
            apellido="gom",
            cedula="345",
            es_menor=True,
        )

        assert len(res.data) == 1
        assert res.data[0].nombre == "Ana"
        assert res.meta.total_records == 1

    def test_filters_by_es_menor_false(self, use_case, fake_repo):
        _seed(fake_repo, 1, menor=True)
        _seed(fake_repo, 1, menor=False)

        res = use_case.execute(
            limite=10,
            estado=None,
            moderacion=None,
            es_menor=False,
        )

        assert len(res.data) == 1
        assert res.data[0].es_menor is False

    def test_filters_by_person_id(self, use_case, fake_repo):
        target_id = uuid4()
        fake_repo._personas.extend(
            [
                PersonaBase(
                    person_id=target_id,
                    estado=Estado.ENCONTRADA,
                    es_menor=False,
                    nombre="Ana",
                    apellido="Gomez",
                    moderacion="aprobada",
                    photos=["https://x/ana.jpg"],
                ),
                PersonaBase(
                    person_id=uuid4(),
                    estado=Estado.ENCONTRADA,
                    es_menor=False,
                    nombre="Luis",
                    apellido="Perez",
                    moderacion="aprobada",
                    photos=["https://x/luis.jpg"],
                ),
            ]
        )

        res = use_case.execute(
            limite=10,
            estado=None,
            moderacion=None,
            person_id=str(target_id),
        )

        assert len(res.data) == 1
        assert res.data[0].person_id == str(target_id)
        assert res.meta.total_records == 1

    def test_filters_by_person_id_case_insensitive(self, use_case, fake_repo):
        target_id = uuid4()
        fake_repo._personas.append(
            PersonaBase(
                person_id=target_id,
                estado=Estado.ENCONTRADA,
                es_menor=False,
                nombre="Ana",
                apellido="Gomez",
                moderacion="aprobada",
                photos=["https://x/ana.jpg"],
            )
        )

        res = use_case.execute(
            limite=10,
            estado=None,
            moderacion=None,
            person_id=str(target_id).upper(),
        )

        assert len(res.data) == 1
        assert res.data[0].person_id == str(target_id)

    def test_filters_by_invalid_person_id_returns_empty(self, use_case, fake_repo):
        fake_repo._personas.append(
            PersonaBase(
                person_id=uuid4(),
                estado=Estado.ENCONTRADA,
                es_menor=False,
                nombre="Ana",
                apellido="Gomez",
                moderacion="aprobada",
                photos=["https://x/ana.jpg"],
            )
        )

        res = use_case.execute(
            limite=10,
            estado=None,
            moderacion=None,
            person_id="invalid-uuid",
        )

        assert len(res.data) == 0
        assert res.meta.total_records == 0

    def test_applies_menores_privacy(self, use_case, fake_repo):
        """Menores: nombre se conserva (ya no se enmascara en admin)."""
        minor = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=True,
            nombre="Pedrito",
            apellido="López",
            moderacion="aprobada",
            photos=["https://x/minor.jpg"],
        )
        fake_repo._personas.append(minor)
        res = use_case.execute(limite=10, estado=None, moderacion=None)
        assert len(res.data) == 1
        assert res.data[0].nombre == "Pedrito"
        assert res.data[0].apellido == "López"

    def test_respects_limite(self, use_case, fake_repo):
        _seed(fake_repo, 10)
        res = use_case.execute(limite=5, estado=None, moderacion=None)
        assert len(res.data) == 5
        assert res.meta.total_records == 10
        assert res.meta.total_pages == 2

    def test_empty_list_when_no_data(self, use_case):
        res = use_case.execute(limite=10, estado=None, moderacion=None)
        assert res.data == []
        assert res.meta.total_records == 0
        assert res.meta.total_pages == 0
