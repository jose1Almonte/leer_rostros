"""Route-level contract tests for admin pagination compatibility."""

import asyncio
from io import BytesIO
from uuid import uuid4

import pytest
from starlette.datastructures import UploadFile

from app.domain.persona import Estado, PersonaBase
from app.schemas import (
    PaginaCandidatos,
    PaginaPersonas,
    PaginaReportes,
    PaginaTestimonios,
)
from tests.personas.repositories.fake import FakePersonaRepository
from tests.reportes.repositories.fake import FakeReporteRepository
from tests.testimonios.use_cases.fake import FakeTestimonioRepository


@pytest.fixture
def fake_repos(monkeypatch):
    import app.main as main

    persona_repo = FakePersonaRepository()
    reporte_repo = FakeReporteRepository()
    testimonio_repo = FakeTestimonioRepository()
    monkeypatch.setattr(main, "_repo", persona_repo)
    monkeypatch.setattr(main, "_reporte_repo", reporte_repo)
    monkeypatch.setattr(main, "_testimonio_repo", testimonio_repo)
    return persona_repo, reporte_repo, testimonio_repo


def _persona(
    *,
    nombre: str,
    apellido: str,
    doc_numero: str,
    es_menor: bool = False,
    estado: Estado = Estado.ENCONTRADA,
):
    return PersonaBase(
        person_id=uuid4(),
        estado=estado,
        es_menor=es_menor,
        nombre=nombre,
        apellido=apellido,
        doc_numero=doc_numero,
        moderacion="aprobada",
        codigo=f"REE-{uuid4().hex[:8].upper()}",
        photos=[f"https://fake-cdn.example.com/personas/{uuid4().hex}.jpg"],
    )


def _testimonio(estado: str = "pendiente") -> dict:
    return {
        "id": str(uuid4()),
        "person_id": str(uuid4()),
        "tipo": "foto",
        "archivo_url": "https://fake-cdn.example.com/testimonios/t.jpg",
        "archivo_key": "testimonios/t.jpg",
        "mime": "image/jpeg",
        "bytes": 100,
        "mensaje": "Test",
        "nombre_testigo": "Test",
        "contacto_testigo": "0412-1111111",
        "estado": estado,
        "created_at": "2024-01-01T00:00:00+00:00",
    }


def test_admin_personas_legacy_array_and_paginated_filters(fake_repos):
    import app.main as main

    persona_repo, _, _ = fake_repos
    ana = _persona(
        nombre="Ana",
        apellido="Gomez",
        doc_numero="12345678",
        es_menor=True,
    )
    persona_repo._personas.extend(
        [
            ana,
            _persona(
                nombre="Luis",
                apellido="Perez",
                doc_numero="87654321",
                es_menor=False,
            ),
        ]
    )

    legacy = main.listar(
        limite=1,
        estado=None,
        moderacion=None,
    )
    assert isinstance(legacy, list)
    assert len(legacy) == 1

    paginated = main.listar_paginated(
        limite=100,
        per_page=10,
        estado=None,
        status="encontrada",
        moderacion=None,
        nombre="an",
        apellido="gom",
        cedula="345",
        doc_numero=None,
        person_id=str(ana.person_id),
        es_menor=True,
        offset=0,
        page=None,
    )
    assert isinstance(paginated, PaginaPersonas)
    assert len(paginated.data) == 1
    assert paginated.data[0].nombre == "Ana"
    assert paginated.data[0].es_menor is True
    assert paginated.meta.total_records == 1
    assert paginated.meta.limit == 10


def test_admin_reportes_legacy_array_and_paginated_envelope(fake_repos):
    import app.main as main

    _, reporte_repo, _ = fake_repos
    reporte_repo.add_falla(descripcion="bug A", url=None, contacto=None)
    reporte_repo.add_falla(descripcion="bug B", url=None, contacto=None)

    legacy = main.listar_reportes(
        tipo=None,
        estado=None,
        limite=1,
    )
    assert isinstance(legacy, list)
    assert len(legacy) == 1

    paginated = main.listar_reportes_paginated(
        tipo=None,
        estado=None,
        limite=1,
        offset=0,
        page=None,
    )
    assert isinstance(paginated, PaginaReportes)
    assert len(paginated.data) == 1
    assert paginated.meta.total_records == 2
    assert paginated.meta.total_pages == 2


def test_admin_testimonios_legacy_array_and_paginated_envelope(fake_repos):
    import app.main as main

    _, _, testimonio_repo = fake_repos
    testimonio_repo._testimonios.extend(
        [_testimonio("pendiente"), _testimonio("aprobada")]
    )

    legacy = main.listar_testimonios_admin(
        estado=None,
        limite=1,
    )
    assert isinstance(legacy, list)
    assert len(legacy) == 1

    paginated = main.listar_testimonios_admin_paginated(
        estado="pendiente",
        limite=1,
        offset=0,
        page=None,
    )
    assert isinstance(paginated, PaginaTestimonios)
    assert len(paginated.data) == 1
    assert paginated.data[0].estado == "pendiente"
    assert paginated.meta.total_records == 1


def test_buscar_admin_legacy_array_and_paginated_envelope(fake_repos, monkeypatch):
    import app.main as main

    persona_repo, _, _ = fake_repos
    persona_repo._personas.extend(
        [
            _persona(nombre="Ana", apellido="Gomez", doc_numero="12345678"),
            _persona(nombre="Luis", apellido="Perez", doc_numero="87654321"),
        ]
    )
    monkeypatch.setattr(
        main.faces,
        "embedding_from_bytes",
        lambda data: (b"fake-embedding", None),
    )

    legacy = asyncio.run(
        main.buscar_admin(
            file=UploadFile(filename="face.jpg", file=BytesIO(b"image-bytes")),
            limite=1,
            estado=None,
        )
    )
    assert isinstance(legacy, list)
    assert len(legacy) == 1

    paginated = asyncio.run(
        main.buscar_admin_paginated(
            file=UploadFile(filename="face.jpg", file=BytesIO(b"image-bytes")),
            limite=1,
            estado=None,
            offset=1,
            page=None,
        )
    )
    assert isinstance(paginated, PaginaCandidatos)
    assert len(paginated.data) == 1
    assert paginated.meta.total_records == 2
    assert paginated.meta.current_page == 2
