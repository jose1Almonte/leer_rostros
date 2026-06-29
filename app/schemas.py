from datetime import datetime

from pydantic import BaseModel, Field


class LoginBody(BaseModel):
    usuario: str = Field("admin", examples=["admin"])
    password: str = Field(..., examples=["reencuentros2026"])


class LoginResp(BaseModel):
    token: str
    tipo: str = "Bearer"


class Candidato(BaseModel):
    """Una persona candidata de una búsqueda, con su grado de parecido."""

    person_id: str
    estado: str = Field(..., description="'buscada' o 'encontrada'.")
    es_menor: bool = False
    nombre: str | None = Field(None, description="Nombre (también en menores). null si no se registró → el front muestra 'Sin nombre registrado'.")
    apellido: str | None = None
    edad: str | None = None
    refugio: str | None = Field(None, description="Refugio donde se encuentra (si fue encontrada).")
    ubicacion: str | None = Field(None, description="Última ubicación conocida / dónde se encontró.")
    telefono: str | None = Field(None, description="Teléfono de contacto para el reencuentro.")
    encontrado_por: str | None = Field(None, description="Nombre de quien encontró a la persona.")
    descripcion: str | None = None
    image_url: str
    distancia: float = Field(..., description="Distancia coseno (menor = más parecido).")
    coincidencia: int = Field(..., description="Porcentaje de coincidencia (0-100).")
    confianza: str = Field(..., description="'alta' | 'media' | 'baja'.")


class PageMeta(BaseModel):
    """Metadatos de paginación (para listados y búsquedas)."""

    total_records: int = Field(..., description="Total de registros que cumplen el filtro (sin paginar).")
    current_page: int = Field(..., description="Página actual (1-based).")
    total_pages: int = Field(..., description="Total de páginas disponibles.")
    limit: int = Field(..., description="Tamaño de página aplicado.")
    offset: int = Field(..., description="Desplazamiento aplicado.")


class ResultadoBusqueda(BaseModel):
    """Respuesta del flujo FAMILIAR: su código + lista de candidatos + paginación.

    `coincidencias` se mantiene por compatibilidad; `meta` trae el total real y las páginas.
    """

    codigo: str = Field(..., description="Código del registro de búsqueda generado.")
    total: int = Field(..., description="Cantidad de coincidencias en ESTA página (len de coincidencias).")
    coincidencias: list[Candidato]
    data: list[Candidato] = Field(
        ...,
        description="Resultados paginados para clientes nuevos; mismos items que coincidencias.",
    )
    meta: PageMeta = Field(..., description="Paginación: total real, página actual y total de páginas.")


class AlertaFamiliar(BaseModel):
    """Aviso cuando un RESCATISTA registra a alguien que un familiar ya buscaba."""

    person_id: str
    familiar_nombre: str | None = None
    familiar_telefono: str | None = None
    image_url: str
    coincidencia: int
    confianza: str
    es_menor: bool = False  # Used by MenoresPrivacy to mask familiar_nombre for minors


class AlertaDuplicado(BaseModel):
    """Aviso de que YA existe una persona encontrada con la misma cédula.

    Se devuelve cuando un rescatista intenta registrar a alguien cuyo documento
    coincide con un encontrado previo. El rescatista decide: si reenvía con
    `confirmar_duplicado=true`, el nuevo avistamiento se agrega al histórico de
    esa persona (no se crea un duplicado)."""

    person_id: str = Field(..., description="ID de la persona ya registrada.")
    codigo: str | None = Field(None, description="Código del registro existente.")
    nombre: str | None = None
    apellido: str | None = None
    doc_numero: str | None = Field(None, description="Documento que coincidió.")
    refugio: str | None = Field(None, description="Refugio actual registrado.")
    ubicacion: str | None = None
    image_url: str | None = None
    es_menor: bool = False
    mensaje: str = Field(
        "Ya existe una persona registrada con esta cédula. "
        "Reenvía con confirmar_duplicado=true para agregar este avistamiento a su histórico.",
        description="Texto orientativo para el front.",
    )


class ResultadoRegistro(BaseModel):
    """Respuesta del flujo RESCATISTA: código + posible alerta de coincidencia."""

    codigo: str = Field(..., description="Código de registro generado.")
    person_id: str
    alerta: AlertaFamiliar | None = Field(None, description="Mejor familiar que ya buscaba a esta persona (match por ROSTRO), si lo hay.")
    coincidencias_familiares: list[AlertaFamiliar] = Field(
        default_factory=list,
        description="Búsqueda INVERSA por cédula: familiares que YA estaban buscando a esta "
        "persona (mismo documento). Vacío si nadie la buscaba o no se dio cédula.",
    )
    alerta_duplicado: AlertaDuplicado | None = Field(
        None,
        description="Si la cédula ya existe entre los encontrados: datos del registro previo. "
        "Si no se confirmó, NO se creó persona nueva.",
    )
    historial_actualizado: bool = Field(
        False,
        description="True si este registro se agregó como avistamiento al histórico de una persona ya existente.",
    )


class EventoHistorial(BaseModel):
    """Un evento del histórico de trazabilidad de una persona encontrada."""

    id: str
    person_id: str
    refugio: str | None = None
    ubicacion: str | None = Field(None, description="Dónde se la vio/encontró en este evento.")
    encontrado_por: str | None = Field(None, description="Quién la reportó en este evento.")
    telefono_responsable: str | None = Field(None, description="Teléfono del responsable en este evento.")
    nota: str | None = Field(None, description="Nota libre (p. ej. 'registro inicial', 'traslado').")
    created_at: datetime = Field(..., description="Timestamp del avistamiento.")


class HistorialEventoIn(BaseModel):
    """Nuevo avistamiento para el histórico de una persona ya registrada."""

    refugio: str | None = Field(None, description="Refugio donde está ahora.", examples=["Refugio Sur, Valencia"])
    ubicacion: str | None = Field(None, description="Dónde se la vio/encontró.", examples=["Av. Bolívar, frente a la plaza"])
    encontrado_por: str | None = Field(None, description="Quién la reporta ahora.", examples=["José (rescatista)"])
    telefono_responsable: str | None = Field(None, description="Teléfono de contacto del responsable.")
    nota: str | None = Field(None, description="Nota libre del evento.", examples=["La trasladaron a otro refugio."])


class ResultadoHistorial(BaseModel):
    """Respuesta al agregar un avistamiento al histórico."""

    person_id: str
    evento: EventoHistorial
    total_eventos: int = Field(..., description="Cantidad total de eventos en el histórico tras agregar este.")


class TrazaPersona(BaseModel):
    """Histórico completo (trazabilidad) de una persona encontrada."""

    person_id: str
    total_eventos: int
    eventos: list[EventoHistorial] = Field(..., description="Eventos en orden cronológico (más antiguo primero).")


class EventoHistorialPublico(BaseModel):
    """Un avistamiento del histórico en su forma PÚBLICA: SIN datos sensibles.

    Igual que `EventoHistorial` pero **omite el teléfono del responsable**. Es lo que
    ve cualquier persona (no admin) al consultar el rastro de un encontrado visible."""

    id: str
    person_id: str
    refugio: str | None = Field(None, description="Refugio donde estaba en este evento.")
    ubicacion: str | None = Field(None, description="Dónde se la vio/encontró en este evento.")
    encontrado_por: str | None = Field(None, description="Quién la reportó en este evento.")
    nota: str | None = Field(None, description="Nota libre (p. ej. 'registro inicial', 'traslado').")
    created_at: datetime = Field(..., description="Timestamp del avistamiento.")


class TrazaPersonaPublica(BaseModel):
    """Histórico PÚBLICO (trazabilidad) de una persona encontrada, sin teléfono.

    Pensado para que **cualquier persona** siga el rastro de un encontrado: dónde ha
    estado y cuándo, en orden cronológico. Solo disponible para personas **visibles**
    (moderación aprobada); el teléfono del responsable NO se incluye (solo el admin lo ve)."""

    person_id: str
    total_eventos: int = Field(..., description="Cantidad de avistamientos en el histórico.")
    eventos: list[EventoHistorialPublico] = Field(
        ..., description="Avistamientos en orden cronológico (el más antiguo primero)."
    )


class FichaPersona(BaseModel):
    """Dossier de una persona: quién la buscaba (inversa por cédula) + su histórico."""

    person_id: str
    doc_numero: str | None = None
    familiares_buscando: list[AlertaFamiliar] = Field(
        default_factory=list,
        description="Familiares que YA buscaban a esta persona (match por cédula). "
        "Cada uno trae su contacto para el reencuentro.",
    )
    total_eventos: int = 0
    eventos: list[EventoHistorial] = Field(
        default_factory=list, description="Histórico de avistamientos (cronológico)."
    )


class ReporteFallaIn(BaseModel):
    """Reporte de una falla/bug de la página."""

    descripcion: str = Field(..., min_length=3, description="Descripción de la falla encontrada.",
                             examples=["Al subir una foto el botón se queda cargando y no pasa nada."])
    url: str | None = Field(None, description="Página/URL donde ocurrió (opcional).",
                            examples=["https://symtechven.com/"])
    contacto: str | None = Field(None, description="Tu email o teléfono para seguimiento (opcional).")


class ReportePublicacionIn(BaseModel):
    """Reporte de una publicación o foto inadecuada."""

    person_id: str = Field(..., description="ID de la publicación reportada (el person_id del candidato).",
                           examples=["992865da-fcc6-4bb2-9db3-3d4af38269ff"])
    descripcion: str = Field(..., min_length=3, description="Motivo del reporte (por qué es inadecuada).",
                             examples=["La foto no corresponde a una persona / contenido ofensivo."])
    contacto: str | None = Field(None, description="Tu contacto para seguimiento (opcional).")


class ReporteCreado(BaseModel):
    """Confirmación de un reporte recibido."""

    id: str
    tipo: str = Field(..., description="'falla' | 'publicacion'.")
    estado: str = Field(..., description="Estado inicial: 'pendiente'.")
    created_at: datetime


class ReporteAdmin(BaseModel):
    """Vista de superadmin de un reporte, con contexto de la publicación si aplica."""

    id: str
    tipo: str = Field(..., description="'falla' | 'publicacion'.")
    descripcion: str
    estado: str = Field(..., description="'pendiente' | 'revisado' | 'resuelto' | 'descartado'.")
    person_id: str | None = None
    url: str | None = None
    contacto: str | None = None
    created_at: datetime
    # Contexto de la publicación reportada (solo si tipo == 'publicacion')
    pub_nombre: str | None = Field(None, description="Nombre de la publicación reportada.")
    pub_estado: str | None = Field(None, description="'buscada' | 'encontrada'.")
    pub_image_url: str | None = None
    pub_moderacion: str | None = Field(None, description="Estado de moderación actual de la publicación.")


class PaginaCandidatos(BaseModel):
    """Listado paginado de candidatos para busquedas admin: `data` + `meta`."""

    data: list[Candidato]
    meta: PageMeta


class PaginaReportes(BaseModel):
    """Listado paginado de reportes para el panel de admin: `data` + `meta`."""

    data: list[ReporteAdmin]
    meta: PageMeta


class ImportarEncontradoIn(BaseModel):
    """Un registro de persona ENCONTRADA para carga masiva (formato de importación).

    La foto se toma de `foto_url` (el server la descarga). Pensado para importar data
    pública existente. Idempotente por `id_externo` (re-importar no duplica)."""

    foto_url: str = Field(..., description="URL pública de la foto del rostro.",
                          examples=["https://terremotovenezuela.app/api/missing/xxxx/photo"])
    nombre: str | None = Field(None, examples=["Ricardo"])
    apellido: str | None = Field(None, examples=["Anselmi"])
    cedula: str | None = Field(None, description="Documento (puede ir vacío).")
    edad: str | None = Field(None, examples=["53"])
    ultima_ubicacion: str | None = Field(None, examples=["Los corales"])
    reportante_phone: str | None = Field(None, description="Contacto de quien reporta (tel/email/texto).")
    reportante_name: str | None = None
    fuente: str | None = Field(None, description="Origen del dato (URL/fuente).")
    id_externo: str | None = Field(None, description="ID en el sistema origen; da idempotencia al import.")


class ImportarResultado(BaseModel):
    """Resultado de importar un registro."""

    estado: str = Field(..., description="'creado' | 'omitido' (ya existía) | error (vía HTTP 4xx).")
    person_id: str | None = None
    codigo: str | None = Field(None, description="Código del registro (= id_externo si se envió).")
    motivo: str | None = None


class PersonaAdmin(BaseModel):
    """Vista de superadmin: registro con sus datos y fotos."""

    person_id: str
    estado: str
    es_menor: bool
    nombre: str | None = None
    apellido: str | None = None
    edad: str | None = None
    doc: str | None = None
    refugio: str | None = None
    ubicacion: str | None = None
    telefono: str | None = None
    codigo: str | None = None
    moderacion: str = "aprobada"
    fotos: list[str]
    created_at: datetime


class TestimonioIn(BaseModel):
    mensaje: str | None = None
    nombre_testigo: str | None = None
    contacto_testigo: str | None = None


class TestimonioCreado(BaseModel):
    id: str
    person_id: str | None = None
    tipo: str
    estado: str = "pendiente"
    created_at: datetime


class TestimonioPublico(BaseModel):
    id: str
    tipo: str
    archivo_url: str
    mensaje: str | None = None
    nombre_testigo: str | None = None
    created_at: datetime


class TestimonioAdmin(BaseModel):
    id: str
    person_id: str | None = None
    tipo: str
    archivo_url: str
    mime: str
    bytes: int
    mensaje: str | None = None
    nombre_testigo: str | None = None
    contacto_testigo: str | None = None
    estado: str
    created_at: datetime
    pub_nombre: str | None = None
    pub_estado: str | None = None
    pub_image_url: str | None = None


class PaginaTestimonios(BaseModel):
    """Listado paginado de testimonios para el panel de admin: `data` + `meta`."""

    data: list[TestimonioAdmin]
    meta: PageMeta


class AdminStats(BaseModel):
    """Conteos reales para el dashboard del superadmin (no dependen de paginación)."""

    total: int = Field(..., description="Total de personas (únicas) en la base.")
    buscadas: int = Field(..., description="Personas en estado 'buscada' (familiares).")
    encontradas: int = Field(..., description="Personas en estado 'encontrada' (rescatistas).")
    menores: int = Field(..., description="Personas marcadas como menores.")
    ocultas: int = Field(..., description="Publicaciones rechazadas (moderacion='rechazada').")
    pendientes_moderacion: int = Field(..., description="Publicaciones pendientes de moderar.")
    reportes_publicaciones: int = Field(..., description="Reportes de publicaciones inadecuadas.")
    reportes_publicaciones_pendientes: int = Field(..., description="…de esos, pendientes.")
    reportes_fallas: int = Field(..., description="Reportes de fallas de la página.")
    reportes_fallas_pendientes: int = Field(..., description="…de esos, pendientes.")
    testimonios_pendientes: int = Field(
        0, description="Testimonios de reencuentro pendientes de moderar."
    )


class PaginaPersonas(BaseModel):
    """Listado paginado de personas para el panel de admin: `data` + `meta`."""

    data: list[PersonaAdmin]
    meta: PageMeta


class PersonaPublica(BaseModel):
    """Vista PÚBLICA de una persona (sin datos sensibles: no teléfono, no documento)."""

    person_id: str
    estado: str
    es_menor: bool = False
    nombre: str | None = Field(None, description="Nombre (null si no se registró o si es menor con baja confianza).")
    apellido: str | None = None
    edad: str | None = None
    ubicacion: str | None = Field(None, description="Refugio / última ubicación conocida.")
    descripcion: str | None = None
    image_url: str | None = None
    created_at: datetime


class PaginaPublica(BaseModel):
    """Listado público paginado: `data` + `meta`. Sin teléfono ni documento."""

    data: list[PersonaPublica]
    meta: PageMeta
