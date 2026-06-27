"""Use-case layer — one class per business flow."""

from app.use_cases.buscar_admin import BuscarAdmin
from app.use_cases.eliminar_persona import EliminarPersona
from app.use_cases.listar_personas_admin import ListarPersonasAdmin
from app.use_cases.moderar_persona import ModerarPersona
from app.use_cases.registrar_busqueda import RegistrarBusqueda
from app.use_cases.registrar_encontrado import RegistrarEncontrado

__all__ = [
    "BuscarAdmin",
    "EliminarPersona",
    "ListarPersonasAdmin",
    "ModerarPersona",
    "RegistrarBusqueda",
    "RegistrarEncontrado",
]
