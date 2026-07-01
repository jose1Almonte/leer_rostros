"""Servicio FastAPI de reencuentros — dos flujos + superadmin.

- POST /buscados    (FAMILIAR)   registra una búsqueda y devuelve los encontrados
                                     más parecidos (con % de coincidencia).
- POST /encontrados (RESCATISTA) registra a una persona hallada y avisa si un
                                     familiar ya la estaba buscando.
- POST /buscar      (ADMIN)      compara una foto contra TODA la base.
- GET  /admin/personas           lista todos los registros.
"""

import uuid
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any

import psycopg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app import faces
from app.auth import (
    create_access_token,
    get_admin_by_username,
    get_current_admin,
    hash_password,
    touch_last_login,
    verify_password,
)
from app.config import get_settings
from app.database import close_pool, get_pool, init_db
from app.domain import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.personas.repositories.persona import PersonaRepository
from app.testimonios.repositories.testimonio import TestimonioRepository
from app.testimonios.use_cases import (
    EliminarTestimonio,
    ListarTestimoniosAdmin,
    ListarTestimoniosPublico,
    ModerarTestimonio,
    RegistrarTestimonio,
)
from app.personas.use_cases import (
    AgregarHistorial,
    BuscarAdmin,
    EliminarPersona,
    ListarCoincidenciasBusqueda,
    ListarPersonasAdmin,
    ListarPublico,
    ModerarPersona,
    RegistrarBusqueda,
    RegistrarEncontrado,
    VerFichaPersona,
    VerTrazabilidad,
    VerTrazabilidadPublica,
    VerificarBuscada,
)
from app.reportes.repositories.reporte import ReporteRepository
from app.reportes.use_cases import (
    CambiarEstadoReporte,
    ListarReportesAdmin,
    RegistrarFalla,
    RegistrarPublicacion,
)
from app.schemas import (
    AdminStats,
    Candidato,
    LoginBody,
    LoginResp,
    PaginaCandidatos,
    PaginaPersonas,
    PaginaPublica,
    PaginaReportes,
    PaginaTestimonios,
    ImportarEncontradoIn,
    ImportarResultado,
    PersonaAdmin,
    ReporteAdmin,
    ReporteCreado,
    ReporteFallaIn,
    ReportePublicacionIn,
    ResultadoBusqueda,
    ResultadoHistorial,
    ResultadoRegistro,
    ResultadoVerificacion,
    TestimonioAdmin,
    TestimonioCreado,
    TestimonioPublico,
    HistorialEventoIn,
    FichaPersona,
    TrazaPersona,
    TrazaPersonaPublica,
)
from app.shared._exceptions import (
    ArchivoInvalidoError,
    ModificacionInvalidaError,
    PersonaNotFoundError,
    PersonaValidationError,
    RostroNoDetectadoError,
    TestimonioNotFoundError,
    TestimonioValidationError,
)
from app.shared._net import descargar_imagen_segura

# Module-level policy and repositories (instantiated in lifespan)
_policy: MatchingPolicy | None = None
_repo: PersonaRepository | None = None
_reporte_repo: ReporteRepository | None = None
_testimonio_repo: TestimonioRepository | None = None


def get_policy() -> MatchingPolicy:
    """Get the matching policy instance."""
    if _policy is None:
        raise RuntimeError("Policy not initialized. Call lifespan first.")
    return _policy


def get_repo() -> PersonaRepository:
    """Get the persona repository instance."""
    if _repo is None:
        raise RuntimeError("Repository not initialized. Call lifespan first.")
    return _repo


def get_reporte_repo() -> ReporteRepository:
    """Get the reporte repository instance."""
    if _reporte_repo is None:
        raise RuntimeError("Repository not initialized. Call lifespan first.")
    return _reporte_repo


def get_testimonio_repo() -> TestimonioRepository:
    """Get the testimonio repository instance."""
    if _testimonio_repo is None:
        raise RuntimeError("Repository not initialized. Call lifespan first.")
    return _testimonio_repo


async def _procesar_fotos(files: list[UploadFile]):
    """Por cada foto con rostro válido, extrae sus embeddings (base + rotaciones ±15°).

    Devuelve `[(data, content_type, [(embedding, calidad), ...]), ...]`, omitiendo las
    fotos sin rostro o de baja calidad."""
    procesadas = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        ct = f.content_type or "image/jpeg"
        try:
            embs = faces.embeddings_from_bytes(data)
        except ValueError:
            continue  # sin rostro / baja calidad: se omite
        procesadas.append((data, ct, embs))
    return procesadas


def _use_case_execute(execute_fn, **kwargs):
    """Call a sync use case execute() with domain exception mapping."""
    try:
        return execute_fn(**kwargs)
    except PersonaValidationError as e:
        raise HTTPException(422, e.message) from None
    except RostroNoDetectadoError as e:
        raise HTTPException(422, e.message) from None
    except PersonaNotFoundError as e:
        raise HTTPException(404, e.message) from None
    except ModificacionInvalidaError as e:
        raise HTTPException(400, e.message) from None
    except ArchivoInvalidoError as e:
        raise HTTPException(422, e.message) from None
    except TestimonioValidationError as e:
        raise HTTPException(422, e.message) from None
    except TestimonioNotFoundError as e:
        raise HTTPException(404, e.message) from None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _policy, _repo, _reporte_repo, _testimonio_repo

    try:
        init_db()
    except (psycopg.errors.DuplicateTable, psycopg.errors.ProgrammingError):
        # Otro worker ganó la carrera de creación de esquema; al reintentar ya existe.
        from contextlib import suppress

        with suppress(psycopg.errors.DuplicateTable, psycopg.errors.ProgrammingError):
            init_db()

    pool = get_pool()
    faces.warmup()

    # Instantiate policy and repositories
    s = get_settings()
    _policy = MatchingPolicy(threshold=s.match_threshold)
    _repo = PersonaRepository(pool=pool, policy=_policy)
    _reporte_repo = ReporteRepository(pool=pool)
    _testimonio_repo = TestimonioRepository(pool=pool)

    # Seed del primer admin desde env vars (idempotente).
    # Si la tabla `admins` está vacía, crea el admin con admin_user/admin_password.
    # Después de esto, esos env vars se IGNORAN para el login (siempre se valida contra BD).
    if s.admin_user and s.admin_password:
        with pool.connection() as conn:
            if get_admin_by_username(conn, s.admin_user) is None:
                conn.execute(
                    "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                    (s.admin_user, hash_password(s.admin_password)),
                )
                conn.commit()
                print(
                    f"[seed] admin '{s.admin_user}' creado desde env vars. "
                    f"Cambiá la password con: python -m app.cli change-password {s.admin_user}",
                    flush=True,
                )
    else:
        with pool.connection() as conn:
            any_admin = conn.execute("SELECT 1 FROM admins LIMIT 1").fetchone()
        if any_admin is None:
            print(
                "[seed] AVISO: no hay admins y ADMIN_USER/ADMIN_PASSWORD están vacíos. "
                "Creá uno con: python -m app.cli create-admin",
                flush=True,
            )

    # Falla rápido si JWT_SECRET no está configurado y alguien podría intentar loguearse.
    if not s.jwt_secret:
        print(
            "[startup] AVISO: JWT_SECRET no está configurado. "
            "El endpoint /admin/login va a fallar hasta que lo setees en .env.",
            flush=True,
        )

    yield
    close_pool()


tags = [
    {"name": "familiar", "description": "Flujo del familiar que busca a alguien."},
    {"name": "rescatista", "description": "Flujo de quien encontró a una persona."},
    {
        "name": "importación",
        "description": "Carga masiva de personas encontradas (admin).",
    },
    {
        "name": "reportes",
        "description": "Reportar fallas de la página o publicaciones inadecuadas.",
    },
    {
        "name": "testimonios",
        "description": "Subir y ver testimonios de reencuentro (foto/video).",
    },
    {"name": "admin", "description": "Superadmin: buscar, moderar y ver reportes."},
    {"name": "sistema", "description": "Estado del servicio."},
]

# Respuestas de error que Swagger debe mostrar para los endpoints protegidos por
# `get_current_admin`. Sin esto, /api/docs no exhibe los 401/403 que el dev debe
# manejar en el front.
_ADMIN_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "description": "Sin token, token expirado, token mal firmado, o admin inexistente."
    },
    403: {"description": "Cuenta de admin desactivada (is_active=false)."},
}

DESCRIPTION = """
API de **reconocimiento facial** para reunir personas desaparecidas con sus familias.

Todas las peticiones de registro/búsqueda son **`multipart/form-data`** (porque suben
foto). La foto va en el campo **`files`** (puedes mandar varias del mismo registro).

---

### 🟣 Flujo FAMILIAR — `POST /buscados`
Un familiar sube la foto de a quién busca. Se registra como *buscada* y se devuelve la
**lista de personas ya encontradas** ordenadas por parecido.

| Campo | Tipo | Obligatorio | Ejemplo |
|---|---|---|---|
| `files` | archivo(s) | **Sí** (con rostro) | foto.jpg |
| `nombre` | texto | no* | `María` |
| `apellido` | texto | no | `Pérez` |
| `edad` | texto | no | `8` |
| `doc_tipo` | texto | no | `V` |
| `doc_numero` | texto | no* | `12345678` |
| `telefono_contacto` | texto | no | `0412-1234567` |
| `limit` / `limite` | entero | no (def. `10`) | `20` |
| `offset` | entero | no (def. `0`) | `20` |
| `page` | entero | no | `2` |

\\* Manda **al menos** `nombre` o `doc_numero` (validación).
El front decide cuántas coincidencias recibir con **`limit`** (1-50). **`limite`**
se mantiene por compatibilidad. **`offset`** / **`page`** permiten cargar más
coincidencias sin traer todo el listado en una sola respuesta. La respuesta incluye
**`data`** y **`meta`** (`total_records`, `current_page`, `total_pages`) además de
`coincidencias` (que se mantiene por compatibilidad).

### 🟢 Flujo RESCATISTA — `POST /encontrados`
Quien encontró a alguien lo registra. Si un familiar ya lo buscaba, la respuesta trae
una **alerta** con el nombre y teléfono del familiar.

> **Flujo INVERSO explícito — `POST /encontrados/verificar`:** el espejo de `/buscados`.
> El rescatista sube una foto y obtiene los **familiares que la están buscando**
> (ordenados por parecido, con su teléfono), **sin registrar nada**. Sirve para
> verificar cuantas veces quiera, antes o después de registrar a la persona.

| Campo | Tipo | Obligatorio | Ejemplo |
|---|---|---|---|
| `files` | archivo(s) | **Sí** (con rostro) | foto.jpg |
| `es_menor` | bool | no (def. `false`) | `true` |
| `nombre` | texto | no | `Juan` |
| `apellido` | texto | no | `Gómez` |
| `doc_tipo` / `doc_numero` | texto | no | `V` / `87654321` |
| `refugio` | texto | **Sí** | `Refugio Central, Caracas` |
| `ubicacion` | texto | no | `Plaza Bolívar` |
| `encontrado_por` | texto | no | `María (vecina)` |
| `telefono_responsable` | texto | **Sí** | `0414-9999999` |
| `doc_responsable` | texto | **Sí si `es_menor`** | `V-11111111` |
| `descripcion` | texto | no | `cabello castaño, 1.20 m` |

> **Menores:** `es_menor=true` marca al niño. Sus datos se **guardan** siempre, pero en
> las **búsquedas** se protegen según la confianza del match: si la `coincidencia` del
> resultado es **≥ 20 %** se muestran `nombre`/`apellido`; si es **< 20 %** llegan como
> `null` (front: *"Sin nombre registrado"*). El **admin** siempre ve los datos reales.
> Cada encontrado expone además **`encontrado_por`** (quién lo halló) y su **teléfono**.

### 🚩 REPORTES (público)
- `POST /reportes/falla` — reportar un bug/falla de la página (JSON: `descripcion`, `url?`, `contacto?`).
- `POST /reportes/publicacion` — reportar una publicación/foto inadecuada (JSON: `person_id`, `descripcion`, `contacto?`).

### 🎉 TESTIMONIOS (público)
Cualquier persona puede **subir un testimonio** (foto o video) si encontró a la persona
que buscaba, para inspirar a otros y cerrar el ciclo.

- `POST /testimonios` — subir un archivo (foto o video) con un mensaje, opcionalmente
  linkeado a un `person_id`. Si **no** se pasa `person_id`, exige `nombre_testigo` +
  `contacto_testigo` para que el admin pueda validar. Los testimonios nuevos arrancan
  en estado `pendiente` hasta que el admin los apruebe.
- `GET /personas/{person_id}/testimonios` — lista **pública** de testimonios aprobados
  de una persona (solo los que tienen `estado=aprobada`).

| Campo | Tipo | Obligatorio | Ejemplo |
|---|---|---|---|
| `archivo` | archivo | **Sí** | foto.jpg o video.mp4 (≤ 50 MB) |
| `person_id` | texto | no | `992865da-...` (UUID) |
| `mensaje` | texto | no | `"¡Gracias! Lo encontramos por esta app."` |
| `nombre_testigo` | texto | depende | `María Pérez` |
| `contacto_testigo` | texto | depende | `0412-1234567` |

\\* Si **no** se envía `person_id`, se exigen `nombre_testigo` y `contacto_testigo`.

### 🛡️ SUPERADMIN

Todos los endpoints de abajo requieren el header **`Authorization: Bearer <token>`**.
El token se obtiene de `POST /admin/login` (abajo).

- `POST /admin/login` — login. Body JSON `{"usuario":"...","password":"..."}`. Devuelve
  un **JWT** firmado (HS256) con expiración (`JWT_EXPIRES_MINUTES`, def. 60 min). La
  validación es **siempre contra la BD** (tabla `admins`, hash bcrypt). La primera
  vez, el admin se siembra automáticamente desde `ADMIN_USER` / `ADMIN_PASSWORD` del
  `.env` si la tabla está vacía. Cambiá la password con
  `python -m app.cli change-password <usuario>`.
- `POST /buscar` — comparar una foto contra TODA la base y devolver array legacy
  (campos `file`, `limite`, `estado`).
- `POST /buscar/paginated` — misma busqueda admin, pero paginada con `limite`,
  `offset`/`page`; devuelve `{data, meta}`.
- `GET /admin/stats` — **conteos reales** para el dashboard (total, buscadas, encontradas,
  menores, ocultas, pendientes, reportes). Usalo para los totales; NO cuentes el largo de
  `/admin/personas` (viene topado por `limite`).
- `GET /admin/personas` — listar registros en array legacy. Query: `limite`,
  `estado`, `moderacion`.
- `GET /admin/personas/paginated` — listar registros paginados. Query: `limite`,
  `offset` o `page`, `per_page`, `estado`/`status`, `moderacion`, `nombre`,
  `apellido`, `cedula`/`doc_numero`, `person_id`, `es_menor`. Devuelve
  **`{data:[...], meta:{total_records, current_page, total_pages, limit, offset}}`**.
  Recorrer todo: `limite=100&page=1`, `page=2`, …
- `PATCH /admin/personas/{person_id}/moderacion?valor=aprobada|rechazada|pendiente` — moderar.
- `DELETE /admin/personas/{person_id}` — borrar.
- `GET /admin/reportes` — ver reportes recibidos en array legacy (filtros `tipo`,
  `estado`, `limite`).
- `GET /admin/reportes/paginated` — ver reportes paginados (filtros `tipo`,
  `estado`; paginacion con `limite`, `offset`/`page`; devuelve `{data, meta}`).
- `PATCH /admin/reportes/{id}/estado` — marcar un reporte (pendiente/revisado/resuelto/descartado).
- `GET /admin/testimonios` — ver testimonios recibidos en array legacy (filtro
  `estado`, `limite`).
- `GET /admin/testimonios/paginated` — ver testimonios paginados (filtro `estado`;
  paginacion con `limite`, `offset`/`page`; devuelve `{data, meta}`).
- `PATCH /admin/testimonios/{id}/estado` — aprobar/rechazar testimonio.
- `DELETE /admin/testimonios/{id}` — eliminar testimonio (borra el archivo).

**Errores comunes en endpoints de admin:**

| Código | Cuándo |
|---|---|
| `401` | Sin header `Authorization`, token mal firmado, token expirado, o el admin ya no existe |
| `403` | El admin existe pero está `is_active=false` (desactivado) |
El body de error siempre es `{"detail": "..."}`. **No hay endpoint de logout**: el
token vive en el front y expira solo; al recibir 401, el front debe volver a llamar
a `POST /admin/login`.

---

### Cómo interpretar la respuesta de búsqueda
Cada candidato trae:
- **`coincidencia`** (0-100): porcentaje de parecido para mostrar al usuario.
- **`confianza`**: `alta` (<0.40, casi seguro) · `media` (0.40-0.55, revisar) · `baja`.
- **`distancia`**: valor técnico (menor = más parecido; 0 = idéntico).
- **`refugio`, `ubicacion`, `telefono`**: datos para el reencuentro (el botón *"Es mi familiar"*).
"""

app = FastAPI(
    title="Reencuentros — Reconocimiento facial",
    description=DESCRIPTION,
    version="2.1.0",
    openapi_tags=tags,
    lifespan=lifespan,
)

# CORS: restringido a orígenes conocidos (producción + local dev).
# Ver `cors_origins` en config.py. Ajustable con CORS_ORIGINS en .env.
# La auth admin va por header Bearer (JWT), por eso allow_credentials=False.
# Nota: CORS lo aplica el NAVEGADOR; no bloquea clientes server-to-server (curl, etc.).
_cors_origins = get_settings().cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["sistema"], summary="Estado del servicio")
def health():
    return {"status": "ok"}


@app.post(
    "/admin/login",
    response_model=LoginResp,
    tags=["admin"],
    summary="Login del superadmin",
)
def admin_login(datos: LoginBody):
    """Devuelve un JWT. Úsalo como header `Authorization: Bearer <token>` en los
    demás endpoints de admin. Body JSON: `{"usuario":"admin","password":"..."}`.

    El login valida SIEMPRE contra la BD (tabla `admins`). El password se compara
    con bcrypt — nunca en plano."""
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, is_active FROM admins WHERE username = %s",
            (datos.usuario,),
        ).fetchone()
    # Mismo error para usuario inexistente, password incorrecta o cuenta inactiva:
    # no le damos pistas a un atacante sobre qué campo falló.
    if row is None or not row[3] or not verify_password(datos.password, row[2]):
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    admin_id, username = row[0], row[1]
    with get_pool().connection() as conn:
        touch_last_login(conn, admin_id)
        conn.commit()
    return LoginResp(token=create_access_token(admin_id, username))


@app.post(
    "/buscados",
    response_model=ResultadoBusqueda,
    status_code=201,
    tags=["familiar"],
    summary="Familiar: registrar búsqueda y ver coincidencias",
)
async def registrar_busqueda(
    files: list[UploadFile] = File(
        ..., description="Foto(s) del rostro de la persona buscada (obligatorio)."
    ),
    nombre: str | None = Form(None, max_length=120),
    apellido: str | None = Form(None, max_length=120),
    edad: str | None = Form(None, max_length=20),
    doc_tipo: str | None = Form(None, max_length=40),
    doc_numero: str | None = Form(None, max_length=40),
    telefono_contacto: str | None = Form(
        None, max_length=120, description="Teléfono del familiar para el reencuentro."
    ),
    limite: int = Form(
        10, description="Tamaño de página (1-50). Cuántas coincidencias por página."
    ),
    limit: int | None = Form(
        None, description="Alias de limite para clientes que usan limit."
    ),
    offset: int = Form(0, description="Cantidad de coincidencias a omitir."),
    page: int | None = Form(
        None, description="Pagina 1-based. Si se envia, tiene prioridad sobre offset."
    ),
):
    procesadas = await _procesar_fotos(files)
    use_case = RegistrarBusqueda(get_repo(), get_policy())
    limite_final = limit if limit is not None else limite
    return _use_case_execute(
        use_case.execute,
        procesadas=procesadas,
        nombre=nombre,
        apellido=apellido,
        edad=edad,
        doc_tipo=doc_tipo,
        doc_numero=doc_numero,
        telefono_contacto=telefono_contacto,
        limite=limite_final,
        offset=offset,
        page=page,
    )


@app.get(
    "/buscados/{codigo}/coincidencias",
    response_model=ResultadoBusqueda,
    tags=["familiar"],
    summary="Familiar: cargar mas coincidencias de una busqueda",
)
def listar_coincidencias_busqueda(
    codigo: str,
    limite: int | None = Query(None, description="Alias legacy de limit."),
    limit: int | None = Query(
        None, description="Cantidad de resultados por pagina (1-50)."
    ),
    offset: int = Query(0, description="Cantidad de resultados a omitir."),
    page: int | None = Query(
        None, description="Pagina 1-based. Si se envia, tiene prioridad sobre offset."
    ),
):
    """Devuelve mas coincidencias de una busqueda existente sin registrarla de nuevo."""
    use_case = ListarCoincidenciasBusqueda(get_repo())
    limite_final = (
        limit if limit is not None else (limite if limite is not None else 10)
    )
    return _use_case_execute(
        use_case.execute,
        codigo=codigo,
        limite=limite_final,
        offset=offset,
        page=page,
    )


@app.post(
    "/encontrados",
    response_model=ResultadoRegistro,
    status_code=201,
    tags=["rescatista"],
    summary="Rescatista: registrar persona encontrada",
)
async def registrar_encontrado(
    files: list[UploadFile] = File(
        ..., description="Foto(s) del rostro de la persona encontrada (obligatorio)."
    ),
    es_menor: bool = Form(
        False, description="Marcar si es menor (etiqueta; el nombre SÍ se guarda/muestra)."
    ),
    nombre: str | None = Form(None, max_length=120, description="Nombre del encontrado (null si no se conoce)."),
    apellido: str | None = Form(None, max_length=120, description="Apellido del encontrado (null si no se conoce)."),
    doc_tipo: str | None = Form(None, max_length=40),
    doc_numero: str | None = Form(None, max_length=40),
    refugio: str | None = Form(None, max_length=300, description="Refugio donde se encuentra."),
    ubicacion: str | None = Form(None, max_length=300, description="Dónde se encontró a la persona."),
    encontrado_por: str | None = Form(
        None, max_length=160, description="Nombre de quien encontró a la persona (se muestra al familiar)."
    ),
    telefono_responsable: str | None = Form(
        None, max_length=120, description="Teléfono de quien lo encontró / responsable."
    ),
    doc_responsable: str | None = Form(
        None, max_length=60, description="Identificación del responsable."
    ),
    descripcion: str | None = Form(None, max_length=2000, description="Descripción física básica."),
    confirmar_duplicado: bool = Form(
        False,
        description="Si la cédula ya existe entre los encontrados, en false solo avisa "
        "(no crea duplicado). En true agrega este avistamiento al histórico de esa persona.",
    ),
):
    procesadas = await _procesar_fotos(files)
    use_case = RegistrarEncontrado(get_repo(), get_policy())
    return _use_case_execute(
        use_case.execute,
        procesadas=procesadas,
        es_menor=es_menor,
        nombre=nombre,
        apellido=apellido,
        doc_tipo=doc_tipo,
        doc_numero=doc_numero,
        refugio=refugio,
        ubicacion=ubicacion,
        encontrado_por=encontrado_por,
        telefono_responsable=telefono_responsable,
        doc_responsable=doc_responsable,
        descripcion=descripcion,
        confirmar_duplicado=confirmar_duplicado,
    )


@app.post(
    "/encontrados/verificar",
    response_model=ResultadoVerificacion,
    tags=["rescatista"],
    summary="Rescatista: ¿alguien está buscando a esta persona? (flujo INVERSO, sin registrar)",
)
async def verificar_buscada(
    files: list[UploadFile] = File(
        ..., description="Foto(s) del rostro de la persona hallada (obligatorio)."
    ),
    limite: int = Form(10, description="Tamaño de página (1-50)."),
    offset: int = Form(0, description="Desplazamiento para paginar (alternativa a page)."),
    page: int | None = Form(None, description="Página 1-based (tiene prioridad sobre offset)."),
):
    """**Flujo INVERSO del rescatista** — el espejo de `POST /buscados`.

    El rescatista sube la foto de una persona hallada y obtiene la lista de
    **familiares que la están buscando** (`buscada`), ordenados por **parecido facial**.
    Cada candidato trae el **teléfono del familiar** para coordinar el reencuentro.

    A diferencia de `POST /encontrados`, **este endpoint NO registra nada**: es solo una
    consulta para *verificar* si alguien busca a esa persona — útil para revisar antes
    (o después) de registrarla, cuantas veces haga falta.

    - Mismo modelo facial (ArcFace buffalo_l) y umbral que las demás búsquedas.
    - Solo familiares **visibles** (moderación aprobada). Menores: nombre protegido.
    - `422` si no se detecta rostro en la(s) foto(s).
    """
    procesadas = await _procesar_fotos(files)
    use_case = VerificarBuscada(get_repo())
    return _use_case_execute(
        use_case.execute, procesadas=procesadas, limite=limite, offset=offset, page=page
    )


@app.post(
    "/encontrados/{person_id}/historial",
    response_model=ResultadoHistorial,
    status_code=201,
    tags=["rescatista"],
    summary="Rescatista: agregar un avistamiento al histórico de una persona",
)
def agregar_historial(person_id: str, evento: HistorialEventoIn):
    """**Trazabilidad — paso 2 (escribir):** registra un nuevo **avistamiento** de una
    persona ya encontrada.

    Úsalo cuando un rescatista vuelve a ver/trasladar a la persona o corrige dónde
    está: se guarda el evento con su **timestamp** y se actualiza la ubicación
    actual de la ficha. Hace falta al menos `refugio` o `ubicacion`.

    **Flujo del historial:**
    1. Al registrar (`POST /encontrados`) se crea el primer evento ("registro inicial").
    2. Cualquier rescatista agrega más avistamientos con **este** endpoint.
    3. **Cualquier persona** consulta el rastro con `GET /encontrados/{person_id}/historial`
       (público, sin teléfono). El admin ve el rastro completo (con teléfono) en
       `GET /admin/personas/{person_id}/historial`.

    `404` si el `person_id` no existe; `422` si no se indica ningún lugar."""
    use_case = AgregarHistorial(get_repo())
    return _use_case_execute(
        use_case.execute,
        person_id=person_id,
        refugio=evento.refugio,
        ubicacion=evento.ubicacion,
        encontrado_por=evento.encontrado_por,
        telefono_responsable=evento.telefono_responsable,
        nota=evento.nota,
    )


@app.get(
    "/encontrados/{person_id}/historial",
    response_model=TrazaPersonaPublica,
    tags=["rescatista"],
    summary="Público: ver el historial (rastro) de una persona encontrada",
)
def ver_historial_publico(person_id: str):
    """**Trazabilidad — paso 3 (leer, público):** **cualquier persona** puede ver el
    **rastro** de una persona encontrada: cada avistamiento con su `ubicacion`,
    `refugio`, quién la reportó (`encontrado_por`), la `nota` y el `timestamp`
    (`created_at`), en **orden cronológico** (el más antiguo primero).

    Pensado para que un familiar siga por dónde ha pasado la persona. **No incluye
    datos sensibles**: el `telefono_responsable` se **omite** (eso solo lo ve el admin
    en `GET /admin/personas/{person_id}/historial`).

    Solo disponible para personas **visibles** (moderación aprobada). `404` si la
    persona no existe o no es visible."""
    use_case = VerTrazabilidadPublica(get_repo())
    return _use_case_execute(use_case.execute, person_id=person_id)


@app.get(
    "/encontrados",
    response_model=PaginaPublica,
    tags=["rescatista"],
    summary="Directorio PÚBLICO de personas encontradas (paginado)",
)
def listar_encontrados_publico(
    limite: int = 24,
    offset: int = 0,
    page: int | None = None,
):
    """Lista pública y paginada de personas **encontradas** (visibles/aprobadas), para
    mostrar un directorio en el front. Devuelve `{data, meta}` SIN datos sensibles
    (no teléfono ni documento). Los menores van con nombre/apellido en `null`.

    Paginar con `limite` + `offset` o `page` (1-based)."""
    use_case = ListarPublico(get_repo())
    return _use_case_execute(
        use_case.execute, estado="encontrada", limite=limite, offset=offset, page=page
    )


@app.post(
    "/buscar",
    response_model=list[Candidato],
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: comparar una foto contra TODA la base",
)
async def buscar_admin(
    file: UploadFile = File(...),
    limite: int = Form(25, description="Cuántas coincidencias devolver (1-50)."),
    estado: str | None = Form(
        None, description="Filtrar por 'buscada' o 'encontrada' (vacío = todas)."
    ),
):
    """Devuelve el array legacy de candidatos para comparar una foto en admin."""
    pagina = await _buscar_admin_pagina(file=file, limite=limite, estado=estado)
    return pagina.data


@app.post(
    "/buscar/paginated",
    response_model=PaginaCandidatos,
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: comparar una foto contra TODA la base (paginado)",
)
async def buscar_admin_paginated(
    file: UploadFile = File(...),
    limite: int = Form(25, description="Cuántas coincidencias devolver (1-50)."),
    estado: str | None = Form(
        None, description="Filtrar por 'buscada' o 'encontrada' (vacío = todas)."
    ),
    offset: int = Form(0, description="Cantidad de resultados a omitir."),
    page: int | None = Form(
        None, description="Pagina 1-based. Si se envia, tiene prioridad sobre offset."
    ),
):
    """Devuelve `{data, meta}` para implementar cargar mas en busqueda admin."""
    return await _buscar_admin_pagina(
        file=file,
        limite=limite,
        estado=estado,
        offset=offset,
        page=page,
    )


async def _buscar_admin_pagina(
    *,
    file: UploadFile,
    limite: int,
    estado: str | None,
    offset: int = 0,
    page: int | None = None,
) -> PaginaCandidatos:
    data = await file.read()
    try:
        embedding, _ = faces.embedding_from_bytes(data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    use_case = BuscarAdmin(get_repo())
    pagina = _use_case_execute(
        use_case.execute,
        embedding=embedding,
        estado=estado,
        limite=limite,
        offset=offset,
        page=page,
    )
    return pagina


@app.get(
    "/admin/personas",
    response_model=list[PersonaAdmin],
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: listar registros",
)
def listar(
    limite: int = 100,
    estado: str | None = None,
    moderacion: str | None = None,
):
    """Lista registros en formato legacy array.

    Para paginacion con metadata y filtros avanzados usa `/admin/personas/paginated`.
    """
    pagina = _listar_personas_admin_pagina(
        limite=limite,
        estado=estado,
        moderacion=moderacion,
    )
    return pagina.data


@app.get(
    "/admin/personas/paginated",
    response_model=PaginaPersonas,
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: listar registros paginados",
)
def listar_paginated(
    limite: int = 100,
    per_page: int | None = Query(None, description="Alias de limite."),
    estado: str | None = None,
    status: str | None = Query(None, description="Alias de estado."),
    moderacion: str | None = None,
    nombre: str | None = None,
    apellido: str | None = None,
    cedula: str | None = None,
    doc_numero: str | None = Query(None, description="Alias de cedula."),
    person_id: str | None = Query(None, description="ID de la publicacion/persona."),
    es_menor: bool | None = None,
    offset: int = 0,
    page: int | None = None,
):
    """Lista registros. Filtra por `estado`/`status`, `moderacion`, `nombre`,
    `apellido`, `cedula`/`doc_numero`, `person_id` y `es_menor`; pagina con
    `limite`/`per_page` + `offset` (ej. `limite=100&offset=100`) o `page` (1-based).

    Devuelve el envelope **`{data:[...], meta:{total_records, current_page,
    total_pages, limit, offset}}`**."""
    return _listar_personas_admin_pagina(
        limite=per_page if per_page is not None else limite,
        estado=estado if estado is not None else status,
        moderacion=moderacion,
        offset=offset,
        page=page,
        nombre=nombre,
        apellido=apellido,
        cedula=cedula if cedula is not None else doc_numero,
        person_id=person_id,
        es_menor=es_menor,
    )


def _listar_personas_admin_pagina(
    *,
    limite: int,
    estado: str | None,
    moderacion: str | None,
    offset: int = 0,
    page: int | None = None,
    nombre: str | None = None,
    apellido: str | None = None,
    cedula: str | None = None,
    person_id: str | None = None,
    es_menor: bool | None = None,
) -> PaginaPersonas:
    use_case = ListarPersonasAdmin(get_repo())
    return _use_case_execute(
        use_case.execute,
        limite=limite,
        estado=estado,
        moderacion=moderacion,
        offset=offset,
        page=page,
        nombre=nombre,
        apellido=apellido,
        cedula=cedula,
        person_id=person_id,
        es_menor=es_menor,
    )


@app.get(
    "/admin/stats",
    response_model=AdminStats,
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: conteos reales para el dashboard",
)
def admin_stats():
    """Devuelve los **totales reales** de la base (no dependen de paginación):
    total de personas, buscadas, encontradas, menores, ocultas, pendientes y reportes.

    Úsalo en el dashboard en vez de contar el largo de `GET /admin/personas`
    (ese viene topado por `limite`)."""
    stats = get_repo().stats()
    stats["testimonios_pendientes"] = get_testimonio_repo().count_pendientes()
    return AdminStats(**stats)


@app.patch(
    "/admin/personas/{person_id}/moderacion",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Aprobar / rechazar una publicación",
)
def moderar(person_id: str, valor: str):
    """`valor` = `aprobada` | `rechazada` | `pendiente`. Las rechazadas no aparecen en búsquedas."""
    use_case = ModerarPersona(get_repo())
    return _use_case_execute(use_case.execute, person_id=person_id, valor=valor)


@app.delete(
    "/admin/personas/{person_id}",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Eliminar una publicación (contenido indebido)",
)
def eliminar(person_id: str):
    """Borra la persona, sus fotos del almacenamiento y sus filas de la BD."""
    use_case = EliminarPersona(get_repo())
    return _use_case_execute(use_case.execute, person_id=person_id)


@app.get(
    "/admin/personas/{person_id}/historial",
    response_model=TrazaPersona,
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Trazabilidad: histórico de avistamientos de una persona",
)
def ver_trazabilidad(person_id: str):
    """**Trazabilidad (vista admin):** el **rastro** completo de una persona encontrada,
    cada avistamiento con su `ubicacion`, quién la reportó y el `timestamp`, en orden
    cronológico. A diferencia de la versión pública
    (`GET /encontrados/{person_id}/historial`), **incluye el teléfono** del responsable,
    por eso es solo de admin y funciona aunque la persona no esté aprobada.
    `404` si no existe."""
    use_case = VerTrazabilidad(get_repo())
    return _use_case_execute(use_case.execute, person_id=person_id)


@app.get(
    "/admin/personas/{person_id}/coincidencias",
    response_model=FichaPersona,
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Ficha: quién buscaba a esta persona (inversa por cédula) + histórico",
)
def ver_ficha_persona(person_id: str):
    """**Búsqueda inversa**: dado un encontrado, devuelve los **familiares que ya lo
    estaban buscando** (match por cédula, con su contacto para el reencuentro) y, en
    el mismo lugar, su **histórico** de avistamientos. Solo admin (datos sensibles).
    `404` si el `person_id` no existe."""
    use_case = VerFichaPersona(get_repo())
    return _use_case_execute(use_case.execute, person_id=person_id)


# ----------------------------- REPORTES -----------------------------


@app.post(
    "/reportes/falla",
    response_model=ReporteCreado,
    status_code=201,
    tags=["reportes"],
    summary="Reportar una falla de la página",
)
def reportar_falla(datos: ReporteFallaIn):
    """Cualquier usuario puede reportar un problema/bug de la web. Queda en estado
    `pendiente` para que el superadmin lo revise en `GET /admin/reportes`."""
    use_case = RegistrarFalla(get_reporte_repo())
    return _use_case_execute(use_case.execute, datos=datos)


@app.post(
    "/reportes/publicacion",
    response_model=ReporteCreado,
    status_code=201,
    tags=["reportes"],
    summary="Reportar una publicación o foto inadecuada",
)
def reportar_publicacion(datos: ReportePublicacionIn):
    """Reporta una publicación inadecuada por su `person_id`. La publicación NO se
    oculta automáticamente: queda registrada para que el superadmin la revise y
    decida (puede rechazarla o eliminarla con los endpoints de moderación)."""
    use_case = RegistrarPublicacion(get_reporte_repo())
    return _use_case_execute(use_case.execute, datos=datos)


@app.get(
    "/admin/reportes",
    response_model=list[ReporteAdmin],
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: ver reportes (fallas y publicaciones)",
)
def listar_reportes(
    tipo: str | None = None,
    estado: str | None = None,
    limite: int = 100,
):
    """Lista reportes en formato legacy array."""
    pagina = _listar_reportes_admin_pagina(
        tipo=tipo,
        estado=estado,
        limite=limite,
    )
    return pagina.data


@app.get(
    "/admin/reportes/paginated",
    response_model=PaginaReportes,
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: ver reportes paginados (fallas y publicaciones)",
)
def listar_reportes_paginated(
    tipo: str | None = None,
    estado: str | None = None,
    limite: int = 100,
    offset: int = 0,
    page: int | None = None,
):
    """Lista los reportes recibidos, del más reciente al más antiguo. Filtra por
    `tipo` ('falla' | 'publicacion') y/o `estado`. Los de publicación traen el
    contexto de la publicación reportada (nombre, foto, estado de moderación).
    Devuelve `{data, meta}`."""
    return _listar_reportes_admin_pagina(
        tipo=tipo,
        estado=estado,
        limite=limite,
        offset=offset,
        page=page,
    )


def _listar_reportes_admin_pagina(
    *,
    tipo: str | None,
    estado: str | None,
    limite: int,
    offset: int = 0,
    page: int | None = None,
) -> PaginaReportes:
    use_case = ListarReportesAdmin(get_reporte_repo())
    return _use_case_execute(
        use_case.execute,
        tipo=tipo,
        estado=estado,
        limite=limite,
        offset=offset,
        page=page,
    )


@app.patch(
    "/admin/reportes/{reporte_id}/estado",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: cambiar el estado de un reporte",
)
def cambiar_estado_reporte(reporte_id: str, valor: str):
    """`valor` = `pendiente` | `revisado` | `resuelto` | `descartado`."""
    use_case = CambiarEstadoReporte(get_reporte_repo())
    return _use_case_execute(
        use_case.execute, reporte_id=reporte_id, valor=valor
    )


# ----------------------------- IMPORTACIÓN MASIVA -----------------------------


def _descargar_imagen(url: str) -> bytes:
    """Descarga una imagen desde una URL pública (para la carga masiva).

    Protegido contra SSRF: rechaza URLs que apunten a IPs internas/metadata y
    revalida en cada redirección. Ver `app.shared._net`.
    """
    return descargar_imagen_segura(url)


@app.post(
    "/encontrados/importar",
    response_model=ImportarResultado,
    status_code=201,
    tags=["importación"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Importar UNA persona encontrada (descarga la foto por URL)",
)
async def importar_encontrado(datos: ImportarEncontradoIn):
    """Registra una persona **encontrada** a partir de un registro de importación:
    descarga la `foto_url`, extrae el/los embeddings y la guarda. Pensado para que un
    script suba grandes volúmenes (ver `cargar_encontrados.py`).

    **Idempotente:** si se envía `id_externo` y ya fue importado, devuelve
    `estado='omitido'` sin duplicar. Validaciones laxas (no exige refugio)."""
    cod = (datos.id_externo or "").strip() or ("REE-" + uuid.uuid4().hex[:8].upper())

    # Idempotencia: si ya importamos este id_externo, no duplicar.
    if datos.id_externo:
        with get_pool().connection() as conn:
            ya = conn.execute(
                "SELECT person_id FROM personas WHERE codigo = %s LIMIT 1", (cod,)
            ).fetchone()
        if ya:
            return ImportarResultado(
                estado="omitido",
                person_id=str(ya[0]),
                codigo=cod,
                motivo="ya importado",
            )

    # Descargar la foto.
    try:
        img = _descargar_imagen(datos.foto_url)
    except Exception as e:
        raise HTTPException(422, f"No se pudo descargar la foto: {e}") from None

    # Extraer rostro(s). Si no hay rostro, se rechaza (no entra basura a la base).
    try:
        embs = faces.embeddings_from_bytes(img)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    # Construir el objeto de dominio PersonaBase (Sergionx way).
    nombre = (datos.nombre or "").strip() or None
    apellido = (datos.apellido or "").strip() or None
    ubic = (datos.ultima_ubicacion or "").strip() or None
    desc_partes = []
    if datos.reportante_name and datos.reportante_name.strip():
        desc_partes.append(f"Reporta: {datos.reportante_name.strip()}")
    if datos.fuente and datos.fuente.strip():
        desc_partes.append(f"Fuente: {datos.fuente.strip()}")
    descripcion = " · ".join(desc_partes) or None

    person_id = uuid.uuid4()
    persona = PersonaBase(
        person_id=person_id,
        estado=Estado.ENCONTRADA,
        es_menor=False,  # data pública: no se oculta el nombre
        nombre=nombre,
        apellido=apellido,
        edad=(datos.edad or None),
        doc_tipo=None,
        doc_numero=((datos.cedula or "").strip() or None),
        telefono_contacto=None,
        telefono_responsable=((datos.reportante_phone or "").strip() or None),
        refugio=ubic,
        ubicacion=ubic,
        descripcion=descripcion,
        codigo=cod,
    )
    with get_pool().connection() as conn:
        get_repo().add(person_id, persona, [(img, "image/jpeg", embs)])
    return ImportarResultado(estado="creado", person_id=str(person_id), codigo=cod)


# ----------------------------- TESTIMONIOS -----------------------------


@app.post(
    "/testimonios",
    response_model=TestimonioCreado,
    status_code=201,
    tags=["testimonios"],
    summary="Subir un testimonio (foto o video) de reencuentro",
)
async def registrar_testimonio(
    archivo: UploadFile = File(
        ..., description="Foto (JPEG/PNG/WebP) o video (MP4/WebM). Tope 50 MB."
    ),
    person_id: str | None = Form(
        None, description="ID de la persona encontrada (UUID, opcional)."
    ),
    mensaje: str | None = Form(
        None, max_length=2000, description="Mensaje de cierre / agradecimiento."
    ),
    nombre_testigo: str | None = Form(
        None, max_length=200, description="Nombre de la persona que sube el testimonio."
    ),
    contacto_testigo: str | None = Form(
        None,
        max_length=200,
        description="Teléfono/email de contacto para validación.",
    ),
):
    data = await archivo.read()
    use_case = RegistrarTestimonio(get_testimonio_repo())
    return _use_case_execute(
        use_case.execute,
        archivo_data=data,
        content_type=(archivo.content_type or "application/octet-stream"),
        person_id=person_id,
        mensaje=mensaje,
        nombre_testigo=nombre_testigo,
        contacto_testigo=contacto_testigo,
    )


@app.get(
    "/personas/{person_id}/testimonios",
    response_model=list[TestimonioPublico],
    tags=["testimonios"],
    summary="Lista pública de testimonios aprobados de una persona",
)
def listar_testimonios_publico(person_id: str):
    use_case = ListarTestimoniosPublico(get_testimonio_repo())
    return _use_case_execute(use_case.execute, person_id=person_id)


@app.get(
    "/admin/testimonios",
    response_model=list[TestimonioAdmin],
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: listar testimonios recibidos",
)
def listar_testimonios_admin(
    estado: str | None = None,
    limite: int = 100,
):
    """Lista testimonios en formato legacy array."""
    pagina = _listar_testimonios_admin_pagina(estado=estado, limite=limite)
    return pagina.data


@app.get(
    "/admin/testimonios/paginated",
    response_model=PaginaTestimonios,
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: listar testimonios recibidos paginados",
)
def listar_testimonios_admin_paginated(
    estado: str | None = None,
    limite: int = 100,
    offset: int = 0,
    page: int | None = None,
):
    """Lista los testimonios recibidos. Filtra por `estado` (`pendiente`, `aprobada`,
    `rechazada`). Los testimonios linkeados a una publicación traen el contexto
    (nombre, foto, estado) de esa publicación. Devuelve `{data, meta}`."""
    return _listar_testimonios_admin_pagina(
        estado=estado,
        limite=limite,
        offset=offset,
        page=page,
    )


def _listar_testimonios_admin_pagina(
    *,
    estado: str | None = None,
    limite: int = 100,
    offset: int = 0,
    page: int | None = None,
) -> PaginaTestimonios:
    use_case = ListarTestimoniosAdmin(get_testimonio_repo())
    return _use_case_execute(
        use_case.execute,
        estado=estado,
        limite=limite,
        offset=offset,
        page=page,
    )


@app.patch(
    "/admin/testimonios/{testimonio_id}/estado",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Aprobar / rechazar un testimonio",
)
def moderar_testimonio(testimonio_id: str, valor: str):
    """`valor` = `aprobada` | `rechazada` | `pendiente`."""
    use_case = ModerarTestimonio(get_testimonio_repo())
    return _use_case_execute(use_case.execute, id=testimonio_id, valor=valor)


@app.delete(
    "/admin/testimonios/{testimonio_id}",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Eliminar un testimonio (borra el archivo)",
)
def eliminar_testimonio(testimonio_id: str):
    """Borra el testimonio y el archivo subido del almacenamiento."""
    use_case = EliminarTestimonio(get_testimonio_repo())
    return _use_case_execute(use_case.execute, id=testimonio_id)
