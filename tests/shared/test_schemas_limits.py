"""Verifica que los esquemas de entrada acotan el largo de los campos de texto
(anti-abuso de almacenamiento en BD)."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    HistorialEventoIn,
    ImportarEncontradoIn,
    ReporteFallaIn,
    ReportePublicacionIn,
    TestimonioIn,
)


def test_reporte_falla_rechaza_descripcion_gigante():
    with pytest.raises(ValidationError):
        ReporteFallaIn(descripcion="x" * 5000)


def test_reporte_falla_acepta_descripcion_normal():
    r = ReporteFallaIn(descripcion="El botón no responde al subir la foto.")
    assert r.descripcion


def test_importar_rechaza_foto_url_gigante():
    with pytest.raises(ValidationError):
        ImportarEncontradoIn(foto_url="https://x.com/" + "a" * 3000)


def test_importar_rechaza_nombre_gigante():
    with pytest.raises(ValidationError):
        ImportarEncontradoIn(foto_url="https://x.com/f.jpg", nombre="N" * 500)


def test_historial_rechaza_nota_gigante():
    with pytest.raises(ValidationError):
        HistorialEventoIn(nota="z" * 5000)


def test_publicacion_rechaza_descripcion_gigante():
    with pytest.raises(ValidationError):
        ReportePublicacionIn(person_id="abc", descripcion="m" * 5000)


def test_testimonio_rechaza_mensaje_gigante():
    with pytest.raises(ValidationError):
        TestimonioIn(mensaje="t" * 5000)
