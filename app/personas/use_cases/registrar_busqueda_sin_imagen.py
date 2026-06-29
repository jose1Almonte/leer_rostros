"""RegistrarBusquedaSinImagen: flujo FAMILIAR sin foto (solo texto)."""

from uuid import uuid4

from app.domain.persona import Estado, PersonaBase
from app.domain.privacy import MenoresPrivacy
from app.personas.repositories.persona import PersonaRepository
from app.schemas import CandidatoTexto, PageMeta, ResultadoBusquedaSinImagen
from app.shared._exceptions import PersonaValidationError
from app.shared._helpers import _gen_codigo, construir_meta, normaliza_paginacion


class RegistrarBusquedaSinImagen:
    """FAMILIAR sin imagen: registra una búsqueda por datos y devuelve coincidencias por texto."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(
        self,
        *,
        nombre: str | None,
        apellido: str | None = None,
        edad: str | None = None,
        es_menor: bool = False,
        doc_tipo: str | None = None,
        doc_numero: str | None = None,
        telefono_contacto: str | None = None,
        descripcion: str | None = None,
        limite: int = 10,
        offset: int = 0,
        page: int | None = None,
    ) -> ResultadoBusquedaSinImagen:
        if not ((nombre and nombre.strip()) or (doc_numero and doc_numero.strip())):
            raise PersonaValidationError("Indica al menos el nombre o el número de identificación.")

        limite, offset = normaliza_paginacion(limite, offset, page)
        person_id = uuid4()
        codigo = _gen_codigo()

        persona = PersonaBase(
            person_id=person_id,
            estado=Estado.BUSCADA,
            es_menor=es_menor,
            nombre=nombre,
            apellido=apellido,
            edad=edad,
            doc_tipo=doc_tipo,
            doc_numero=doc_numero,
            telefono_contacto=telefono_contacto,
            descripcion=descripcion,
            moderacion="aprobada",
            codigo=codigo,
        )
        self._repo.add_sin_imagen(person_id, persona)

        # Buscar coincidencias por TEXTO entre los ENCONTRADOS visibles.
        encontrados = self._repo.buscar_por_texto(
            estado="encontrada",
            nombre=nombre,
            apellido=apellido,
            doc_numero=doc_numero,
            limite=limite,
            offset=offset,
        )
        total = self._repo.count_por_texto(
            estado="encontrada", nombre=nombre, apellido=apellido, doc_numero=doc_numero
        )
        candidatos = [MenoresPrivacy(CandidatoTexto(**d)) for d in encontrados]
        return ResultadoBusquedaSinImagen(
            codigo=codigo,
            person_id=str(person_id),
            total=len(candidatos),
            coincidencias=candidatos,
            meta=PageMeta(**construir_meta(total, limite, offset)),
        )
