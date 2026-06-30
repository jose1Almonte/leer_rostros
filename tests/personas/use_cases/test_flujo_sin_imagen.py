"""Tests del flujo SIN IMAGEN (registro y búsqueda por texto)."""

from uuid import uuid4

import pytest

from app.domain.persona import Estado, PersonaBase
from app.personas.use_cases import (
    BuscarPorTexto,
    RegistrarBusquedaSinImagen,
    RegistrarEncontradoSinImagen,
)
from app.schemas import ResultadoBusquedaSinImagen, ResultadoBusquedaTexto
from app.shared._exceptions import PersonaValidationError
from tests.personas.repositories.fake import FakePersonaRepository


@pytest.fixture
def repo():
    return FakePersonaRepository()


def _persona(estado, *, nombre=None, apellido=None, doc=None, es_menor=False,
             telefono=None, refugio=None, moderacion="aprobada"):
    return PersonaBase(
        person_id=uuid4(),
        estado=estado,
        es_menor=es_menor,
        nombre=nombre,
        apellido=apellido,
        doc_numero=doc,
        telefono_contacto=telefono,
        telefono_responsable=telefono,
        refugio=refugio,
        moderacion=moderacion,
        codigo=f"REE-{uuid4().hex[:8].upper()}",
    )


# --------------------------- registrar buscado sin imagen ---------------------------

def test_registrar_buscado_persiste_y_matchea_por_cedula(repo):
    # Hay un encontrado con cédula 12345678
    enc = _persona(Estado.ENCONTRADA, nombre="Juan", apellido="Pérez",
                   doc="12345678", refugio="Refugio Central")
    repo.add_sin_imagen(enc.person_id, enc)

    uc = RegistrarBusquedaSinImagen(repo)
    res = uc.execute(nombre="Juan", doc_numero="12345678", telefono_contacto="0412-1")

    assert isinstance(res, ResultadoBusquedaSinImagen)
    assert res.total == 1
    c = res.coincidencias[0]
    assert c.coincidencia == 100 and c.tipo_match == "documento" and c.confianza == "alta"
    assert c.estado == "encontrada"
    assert c.image_url == ""  # sin imagen
    # El buscado quedó registrado (buscada + encontrada en el repo)
    estados = sorted(p.estado.value for p in repo._personas)
    assert estados == ["buscada", "encontrada"]


def test_registrar_buscado_matchea_por_nombre_parcial(repo):
    enc = _persona(Estado.ENCONTRADA, nombre="María Fernanda", apellido="Gómez",
                   doc="999", refugio="Sur")
    repo.add_sin_imagen(enc.person_id, enc)

    uc = RegistrarBusquedaSinImagen(repo)
    res = uc.execute(nombre="maría")
    assert res.total == 1
    assert res.coincidencias[0].tipo_match == "nombre"
    assert 0 < res.coincidencias[0].coincidencia < 100


def test_registrar_buscado_sin_datos_falla(repo):
    uc = RegistrarBusquedaSinImagen(repo)
    with pytest.raises(PersonaValidationError):
        uc.execute(nombre=None, doc_numero=None)


# ------------------------ registrar encontrado sin imagen (inverso) -----------------

def test_registrar_encontrado_devuelve_buscadas_inverso(repo):
    # Un familiar ya busca la cédula 555
    bus = _persona(Estado.BUSCADA, nombre="Ana", apellido="Ruiz", doc="555",
                   telefono="0414-9")
    repo.add_sin_imagen(bus.person_id, bus)

    uc = RegistrarEncontradoSinImagen(repo)
    res = uc.execute(nombre="Ana", doc_numero="555", refugio="Refugio Norte")

    assert res.total == 1
    c = res.coincidencias[0]
    assert c.estado == "buscada"
    assert c.coincidencia == 100
    assert c.telefono == "0414-9"  # contacto del familiar


# --------------------------------- buscar por texto ---------------------------------

def test_buscar_por_texto_no_registra_nada(repo):
    enc = _persona(Estado.ENCONTRADA, nombre="Pedro", doc="abc")
    repo.add_sin_imagen(enc.person_id, enc)

    uc = BuscarPorTexto(repo)
    res = uc.execute(nombre="Pedro", estado="encontrada")
    assert isinstance(res, ResultadoBusquedaTexto)
    assert res.total == 1
    # No se agregó nada nuevo (sigue habiendo 1 persona)
    assert len(repo._personas) == 1


def test_buscar_por_texto_sin_criterios_falla(repo):
    uc = BuscarPorTexto(repo)
    with pytest.raises(PersonaValidationError):
        uc.execute(nombre=None, apellido=None, doc_numero=None)


def test_buscar_por_texto_paginacion(repo):
    for i in range(5):
        p = _persona(Estado.ENCONTRADA, nombre=f"Carlos {i}", apellido="Díaz")
        repo.add_sin_imagen(p.person_id, p)

    uc = BuscarPorTexto(repo)
    pag1 = uc.execute(apellido="Díaz", estado="encontrada", limite=2, page=1)
    pag2 = uc.execute(apellido="Díaz", estado="encontrada", limite=2, page=2)
    assert pag1.meta.total_records == 5
    assert pag1.meta.total_pages == 3
    assert len(pag1.coincidencias) == 2
    assert len(pag2.coincidencias) == 2
    ids1 = {c.person_id for c in pag1.coincidencias}
    ids2 = {c.person_id for c in pag2.coincidencias}
    assert ids1.isdisjoint(ids2)


def test_buscar_por_texto_respeta_estado(repo):
    enc = _persona(Estado.ENCONTRADA, nombre="Sofía", doc="1")
    bus = _persona(Estado.BUSCADA, nombre="Sofía", doc="2")
    repo.add_sin_imagen(enc.person_id, enc)
    repo.add_sin_imagen(bus.person_id, bus)

    uc = BuscarPorTexto(repo)
    solo_enc = uc.execute(nombre="Sofía", estado="encontrada")
    solo_bus = uc.execute(nombre="Sofía", estado="buscada")
    ambos = uc.execute(nombre="Sofía", estado=None)
    assert {c.estado for c in solo_enc.coincidencias} == {"encontrada"}
    assert {c.estado for c in solo_bus.coincidencias} == {"buscada"}
    assert ambos.total == 2


def test_menor_con_match_por_cedula_muestra_nombre(repo):
    # Menor encontrado: con cédula exacta (coincidencia 100 >= 20) el nombre SÍ se muestra.
    enc = _persona(Estado.ENCONTRADA, nombre="Lucía", apellido="Mora",
                   doc="77", es_menor=True)
    repo.add_sin_imagen(enc.person_id, enc)

    uc = BuscarPorTexto(repo)
    res = uc.execute(doc_numero="77", estado="encontrada")
    assert res.coincidencias[0].es_menor is True
    assert res.coincidencias[0].nombre == "Lucía"
