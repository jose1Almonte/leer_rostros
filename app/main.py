"""Servicio FastAPI de reencuentros — dos flujos + superadmin.

- POST /buscados    (FAMILIAR)   registra una búsqueda y devuelve los encontrados
                                     más parecidos (con % de coincidencia).
- POST /encontrados (RESCATISTA) registra a una persona hallada y avisa si un
                                     familiar ya la estaba buscando.
- POST /buscar      (ADMIN)      compara una foto contra TODA la base.
- GET  /admin/personas           lista todos los registros.
"""

from contextlib import asynccontextmanager
from functools import wraps
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile

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
from app.repositories import PersonaRepository
from app.schemas import (
    Candidato,
    LoginBody,
    LoginResp,
    PersonaAdmin,
    ResultadoBusqueda,
    ResultadoRegistro,
)
from app.use_cases import (
    BuscarAdmin,
    EliminarPersona,
    ListarPersonasAdmin,
    ModerarPersona,
    RegistrarBusqueda,
    RegistrarEncontrado,
)
from app.use_cases._exceptions import (
    ModificacionInvalidaError,
    PersonaNotFoundError,
    PersonaValidationError,
    RostroNoDetectadoError,
)

# Module-level policy and repository (instantiated in lifespan)
_policy: MatchingPolicy | None = None
_repo: PersonaRepository | None = None


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _policy, _repo

    try:
        init_db()
    except Exception:
        # Otro worker ganó la carrera de creación de esquema; al reintentar ya existe.
        from contextlib import suppress

        with suppress(Exception):
            init_db()

    pool = get_pool()
    faces.warmup()

    # Instantiate policy and repository
    s = get_settings()
    _policy = MatchingPolicy(threshold=s.match_threshold)
    _repo = PersonaRepository(pool=pool, policy=_policy)

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
    {"name": "admin", "description": "Superadmin: buscar y comparar imágenes."},
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
| `limite` | entero | no (def. `10`) | `20` |

\\* Manda **al menos** `nombre` o `doc_numero` (validación).
El front decide cuántas coincidencias recibir con **`limite`** (1-50).

### 🟢 Flujo RESCATISTA — `POST /encontrados`
Quien encontró a alguien lo registra. Si un familiar ya lo buscaba, la respuesta trae
una **alerta** con el nombre y teléfono del familiar.

| Campo | Tipo | Obligatorio | Ejemplo |
|---|---|---|---|
| `files` | archivo(s) | **Sí** (con rostro) | foto.jpg |
| `es_menor` | bool | no (def. `false`) | `true` |
| `nombre` | texto | no | `Juan` |
| `apellido` | texto | no | `Gómez` |
| `doc_tipo` / `doc_numero` | texto | no | `V` / `87654321` |
| `refugio` | texto | **Sí** | `Refugio Central, Caracas` |
| `ubicacion` | texto | no | `Plaza Bolívar` |
| `telefono_responsable` | texto | **Sí** | `0414-9999999` |
| `doc_responsable` | texto | **Sí si `es_menor`** | `V-11111111` |
| `descripcion` | texto | no | `cabello castaño, 1.20 m` |

> **Protocolo de menor:** si `es_menor=true`, el `nombre`/`apellido` se guardan en la BD
> pero se ocultan en las respuestas de la API (protección de menores).

### 🛡️ SUPERADMIN

Todos los endpoints de abajo requieren el header **`Authorization: Bearer <token>`**.
El token se obtiene de `POST /admin/login` (abajo).

- `POST /admin/login` — login. Body JSON `{"usuario":"...","password":"..."}`. Devuelve
  un **JWT** firmado (HS256) con expiración (`JWT_EXPIRES_MINUTES`, def. 60 min). La
  validación es **siempre contra la BD** (tabla `admins`, hash bcrypt). La primera
  vez, el admin se siembra automáticamente desde `ADMIN_USER` / `ADMIN_PASSWORD` del
  `.env` si la tabla está vacía. Cambiá la password con
  `python -m app.cli change-password <usuario>`.
- `POST /buscar` — comparar una foto contra TODA la base (campos `file`, `limite`, `estado`).
- `GET /admin/personas` — listar registros. Query: `limite`, `estado`, `moderacion`.
- `PATCH /admin/personas/{person_id}/moderacion?valor=aprobada|rechazada|pendiente` — moderar.
- `DELETE /admin/personas/{person_id}` — borrar.

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
    nombre: str | None = Form(None),
    apellido: str | None = Form(None),
    edad: str | None = Form(None),
    doc_tipo: str | None = Form(None),
    doc_numero: str | None = Form(None),
    telefono_contacto: str | None = Form(
        None, description="Teléfono del familiar para el reencuentro."
    ),
    limite: int = Form(
        10, description="Cuántas coincidencias devolver (1-50). El front lo decide."
    ),
):
    procesadas = await _procesar_fotos(files)
    use_case = RegistrarBusqueda(get_repo(), get_policy())
    return _use_case_execute(
        use_case.execute,
        procesadas=procesadas,
        nombre=nombre,
        apellido=apellido,
        edad=edad,
        doc_tipo=doc_tipo,
        doc_numero=doc_numero,
        telefono_contacto=telefono_contacto,
        limite=limite,
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
        False, description="Activar si es menor de edad (oculta datos sensibles)."
    ),
    nombre: str | None = Form(None),
    apellido: str | None = Form(None),
    doc_tipo: str | None = Form(None),
    doc_numero: str | None = Form(None),
    refugio: str | None = Form(None, description="Refugio donde se encuentra."),
    ubicacion: str | None = Form(None, description="Dónde se encontró a la persona."),
    telefono_responsable: str | None = Form(
        None, description="Teléfono del responsable."
    ),
    doc_responsable: str | None = Form(
        None, description="Identificación del responsable."
    ),
    descripcion: str | None = Form(None, description="Descripción física básica."),
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
        telefono_responsable=telefono_responsable,
        doc_responsable=doc_responsable,
        descripcion=descripcion,
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
    data = await file.read()
    try:
        embedding, _ = faces.embedding_from_bytes(data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    use_case = BuscarAdmin(get_repo())
    return _use_case_execute(
        use_case.execute, embedding=embedding, estado=estado, limite=limite
    )


@app.get(
    "/admin/personas",
    response_model=list[PersonaAdmin],
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
    responses=_ADMIN_RESPONSES,
    summary="Superadmin: listar registros",
)
def listar(limite: int = 100, estado: str | None = None, moderacion: str | None = None):
    """Lista registros. Filtra por estado y/o moderación (para revisar/aprobar)."""
    use_case = ListarPersonasAdmin(get_repo())
    return _use_case_execute(
        use_case.execute, limite=limite, estado=estado, moderacion=moderacion
    )


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
