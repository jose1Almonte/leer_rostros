"""Personas use cases — one class per business flow."""

from app.personas.use_cases.buscar_admin import BuscarAdmin
from app.personas.use_cases.eliminar_persona import EliminarPersona
from app.personas.use_cases.listar_coincidencias_busqueda import ListarCoincidenciasBusqueda
from app.personas.use_cases.listar_personas_admin import ListarPersonasAdmin
from app.personas.use_cases.listar_publico import ListarPublico
from app.personas.use_cases.moderar_persona import ModerarPersona
from app.personas.use_cases.registrar_busqueda import RegistrarBusqueda
from app.personas.use_cases.registrar_encontrado import RegistrarEncontrado

__all__ = [
    "BuscarAdmin",
    "EliminarPersona",
    "ListarCoincidenciasBusqueda",
    "ListarPersonasAdmin",
    "ListarPublico",
    "ModerarPersona",
    "RegistrarBusqueda",
    "RegistrarEncontrado",
]
