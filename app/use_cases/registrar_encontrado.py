"""RegistrarEncontrado use case: RESCATISTA flow."""

from uuid import uuid4

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.domain.privacy import MenoresPrivacy
from app.repositories.persona import PersonaRepository
from app.schemas import AlertaFamiliar, ResultadoRegistro
from app.use_cases._exceptions import PersonaValidationError, RostroNoDetectadoError
from app.use_cases._helpers import ProcessedPhotos, _embedding_consulta, _gen_codigo


class RegistrarEncontrado:
    """RESCATISTA flow: register a found person, alert if a family match exists."""

    def __init__(self, repo: PersonaRepository, policy: MatchingPolicy):
        self._repo = repo
        self._policy = policy

    def execute(
        self,
        *,
        procesadas: ProcessedPhotos,
        es_menor: bool,
        nombre: str | None,
        apellido: str | None,
        doc_tipo: str | None,
        doc_numero: str | None,
        refugio: str | None,
        ubicacion: str | None,
        telefono_responsable: str | None,
        doc_responsable: str | None,
        descripcion: str | None,
    ) -> ResultadoRegistro:
        """Register a found person and return registration result with optional alert.

        Validation rules:
        1. At least one photo with a detected face.
        2. refugio is required.
        3. telefono_responsable is required.
        4. If es_menor=True, doc_responsable is required.

        Returns:
            ResultadoRegistro with codigo, person_id, and optional alerta.

        Raises:
            RostroNoDetectadoError: If no faces detected.
            PersonaValidationError: If required fields are missing.
        """
        # Validation
        if not procesadas:
            raise RostroNoDetectadoError("No se detectó ningún rostro en la(s) foto(s).")
        if not refugio or not refugio.strip():
            raise PersonaValidationError("El refugio actual es obligatorio.")
        if not telefono_responsable or not telefono_responsable.strip():
            raise PersonaValidationError("El teléfono del responsable es obligatorio.")
        if es_menor and not (doc_responsable and doc_responsable.strip()):
            raise PersonaValidationError(
                "Para un menor, la identificación del responsable es obligatoria."
            )

        # Build domain object
        person_id = uuid4()
        codigo = _gen_codigo()

        persona = PersonaBase(
            person_id=person_id,
            estado=Estado.ENCONTRADA,
            es_menor=es_menor,
            nombre=nombre,
            apellido=apellido,
            doc_tipo=doc_tipo,
            doc_numero=doc_numero,
            refugio=refugio,
            ubicacion=ubicacion,
            telefono_responsable=telefono_responsable,
            doc_responsable=doc_responsable,
            descripcion=descripcion,
            moderacion="pendiente",
            codigo=codigo,
        )

        # Persist
        self._repo.add(person_id, persona, procesadas)

        # Cross-flow search for matching buscada
        embedding = _embedding_consulta(procesadas)
        buscados = self._repo.search_by_estado(embedding, "buscada", 1)

        # Build alert if match exists
        alerta = None
        if buscados:
            best = buscados[0]
            d = best["distancia"]
            if self._policy.is_match(d):
                alerta = AlertaFamiliar(
                    person_id=best["person_id"],
                    familiar_nombre=best["nombre"],
                    familiar_telefono=best["telefono"],
                    image_url=best["image_url"],
                    coincidencia=best["coincidencia"],
                    confianza=best["confianza"],
                    es_menor=best["es_menor"],
                )
                alerta = MenoresPrivacy(alerta)

        return ResultadoRegistro(
            codigo=codigo,
            person_id=str(person_id),
            alerta=alerta,
        )
