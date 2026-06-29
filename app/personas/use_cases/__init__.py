"""Personas use cases — one class per business flow."""

from app.personas.use_cases.agregar_historial import AgregarHistorial
from app.personas.use_cases.buscar_admin import BuscarAdmin
from app.personas.use_cases.buscar_por_texto import BuscarPorTexto
from app.personas.use_cases.eliminar_persona import EliminarPersona
from app.personas.use_cases.listar_coincidencias_busqueda import ListarCoincidenciasBusqueda
from app.personas.use_cases.listar_personas_admin import ListarPersonasAdmin
from app.personas.use_cases.listar_publico import ListarPublico
from app.personas.use_cases.moderar_persona import ModerarPersona
from app.personas.use_cases.registrar_busqueda import RegistrarBusqueda
from app.personas.use_cases.registrar_busqueda_sin_imagen import RegistrarBusquedaSinImagen
from app.personas.use_cases.registrar_encontrado import RegistrarEncontrado
from app.personas.use_cases.registrar_encontrado_sin_imagen import RegistrarEncontradoSinImagen
from app.personas.use_cases.ver_ficha_persona import VerFichaPersona
from app.personas.use_cases.ver_trazabilidad import VerTrazabilidad
from app.personas.use_cases.ver_trazabilidad_publica import VerTrazabilidadPublica
from app.personas.use_cases.verificar_buscada import VerificarBuscada

__all__ = [
    "AgregarHistorial",
    "BuscarAdmin",
    "BuscarPorTexto",
    "EliminarPersona",
    "ListarCoincidenciasBusqueda",
    "ListarPersonasAdmin",
    "ListarPublico",
    "ModerarPersona",
    "RegistrarBusqueda",
    "RegistrarBusquedaSinImagen",
    "RegistrarEncontrado",
    "RegistrarEncontradoSinImagen",
    "VerFichaPersona",
    "VerTrazabilidad",
    "VerTrazabilidadPublica",
    "VerificarBuscada",
]
