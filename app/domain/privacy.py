"""Menores privacy protocol: mask names at API response boundary."""

from typing import TypeVar

from app.schemas import AlertaDuplicado, AlertaFamiliar, Candidato, CandidatoTexto, PersonaAdmin

T = TypeVar("T", Candidato, CandidatoTexto, PersonaAdmin, AlertaFamiliar, AlertaDuplicado)


# % mínimo de coincidencia para mostrar los datos de un MENOR en una búsqueda.
# Por debajo de esto el match no es suficientemente confiable → se ocultan sus datos.
MENOR_MIN_COINCIDENCIA = 20


def MenoresPrivacy(obj: T) -> T:
    """Protege los datos de MENORES según la confianza del match.

    Reglas (solo si `es_menor` es True):
      - PersonaAdmin (vista admin): el admin SIEMPRE ve los datos reales.
      - Candidato / AlertaFamiliar (resultados de búsqueda):
          * coincidencia >= 20 %  → se muestran nombre/apellido del menor.
          * coincidencia <  20 %  → se ocultan (nombre/apellido = None;
            para AlertaFamiliar, familiar_nombre = None).

    Adultos: nunca se enmascara. El objeto original no se muta (devuelve copia).
    """
    if not getattr(obj, "es_menor", False):
        return obj

    # El admin ve todo (la vista admin no trae % de coincidencia).
    if isinstance(obj, PersonaAdmin):
        return obj

    coincidencia = getattr(obj, "coincidencia", 0) or 0
    if coincidencia >= MENOR_MIN_COINCIDENCIA:
        return obj  # match confiable → se muestran los datos del menor

    if isinstance(obj, AlertaFamiliar):
        return obj.model_copy(update={"familiar_nombre": None})
    return obj.model_copy(update={"nombre": None, "apellido": None})
