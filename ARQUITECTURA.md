# Arquitectura — Reencuentros (reconocimiento facial)

App de reconocimiento facial para **reunir personas desaparecidas con sus familias**.
Un familiar sube la foto de a quién busca; un rescatista sube la foto de a quién
encontró; el sistema hace **match facial automático** y muestra candidatos para que
una persona confirme.

> Caso de uso real: identificación de personas (incl. niños que no hablan o adultos
> en shock) en emergencias. Por eso prioriza **precisión** sobre velocidad.

---

## 1. Vista general

```
                           ┌─────────────────────────────────────────────┐
       Navegador           │             Droplet DigitalOcean            │
      (rescatista /        │                                             │
       familiar /          │   ┌─────────┐      ┌───────────────────┐    │
       admin)              │   │  nginx  │─────▶│  FastAPI (uvicorn │    │
           │   HTTPS        │   │  :443   │ /api │  + pm2, N workers)│    │
           └──────────────▶ │   │  SSL    │─────▶│   InsightFace     │    │
       symtechven.com       │   │         │  /   │   buffalo_l       │    │
                            │   │         │      │   (ArcFace+Rface) │    │
                            │   └────┬────┘      └─────────┬─────────┘    │
                            │        │                     │              │
                            │   frontend                   │              │
                            │  (HTML estático)   ┌──────────┴───────────┐  │
                            │                    ▼                      ▼  │
                            │            ┌───────────────┐   ┌─────────────┐
                            │            │ Postgres 16 + │   │  Volumen 20GB│
                            │            │ pgvector      │   │ (datos, venv,│
                            │            │ (índice HNSW) │   │  pesos, PG)  │
                            │            └───────────────┘   └─────────────┘
                            └───────────────┬─────────────────────────────┘
                                            │  (URL de la imagen)
                                            ▼
                                ┌───────────────────────────┐
                                │ DigitalOcean Spaces (S3)  │
                                │  bucket: flowcheckapp      │  ← imágenes originales
                                └───────────────────────────┘
```

Despliegue reproducible con **docker-compose** (ver `DOCKER.md` y `DEPLOY.md`).
`Dockerfile.standalone` y `docker/standalone/*` cubren el empaquetado single-image.

---

## 2. Componentes

| Componente | Tecnología | Rol |
|---|---|---|
| **Frontend** | HTML/CSS/JS estático (`frontend/index.html`) | Registrar y buscar desde el navegador (3 pestañas: familiar / rescatista / admin) |
| **Reverse proxy** | nginx + Certbot (SSL) | Sirve el frontend en `symtechven.com` y enruta `/api/` → uvicorn |
| **API** | FastAPI + uvicorn, gestionada por **pm2** | Endpoints REST; doc Swagger en `/api/docs` |
| **Motor facial** | **InsightFace buffalo_l** (ArcFace w600k_r50, 512-dim) + **RetinaFace** (detector) | Convierte rostro → vector de 512 dimensiones + augmentaciones por rotación |
| **Base vectorial** | PostgreSQL 16 + **pgvector** (índice **HNSW**, distancia coseno) | Guarda vectores y busca por similitud |
| **Almacenamiento** | DigitalOcean **Spaces** (S3-compatible, `boto3`) con fallback a disco local | Guarda las imágenes originales |
| **Auth admin** | **JWT (HS256) + bcrypt**, tabla `admins` | Protege los endpoints de superadmin |
| **CLI admin** | `python -m app.cli` | Gestión de cuentas admin (create / change-password / activate / deactivate / list) |

---

## 3. Capas del backend

```
app/
  main.py              # FastAPI: endpoints + lifespan + acceso a policy/repo
  config.py            # Settings (pydantic-settings), cargado desde .env
  database.py          # psycopg pool, init_db, pgvector, HNSW, tabla admins
  faces.py             # InsightFace buffalo_l: detección + embedding + augmentaciones
  storage.py           # subida a DigitalOcean Spaces (boto3) con fallback local
  auth.py              # JWT + bcrypt + guard get_current_admin
  cli.py               # gestión de admins (create / password / list / activate)
  schemas.py           # modelos Pydantic (LoginBody, Candidato, AlertaFamiliar, …)
  domain/              # capa: lógica de dominio pura, sin SQL ni HTTP
    __init__.py        #   barrel
    matching.py        #   MatchingPolicy (is_match, confidence_band, match_percentage)
    privacy.py         #   MenoresPrivacy (mask de nombres de menores)
    persona.py         #   Estado enum, Foto dataclass, PersonaBase model
  repositories/        # capa: toda la SQL del modelo
    __init__.py        #   barrel
    persona.py         #   PersonaRepository: SQL de personas + persona_embeddings
  use_cases/           # ⭐ capa: una clase por flujo de negocio
    __init__.py        #   barrel (re-exporta las 6 clases)
    _exceptions.py     #   excepciones de dominio (PersonaValidationError, …)
    _helpers.py        #   LIMITE_MAX, _gen_codigo, _embedding_consulta
    registrar_busqueda.py     #   POST /buscados (FAMILIAR)
    registrar_encontrado.py   #   POST /encontrados (RESCATISTA) + alerta
    buscar_admin.py           #   POST /buscar (ADMIN)
    listar_personas_admin.py  #   GET /admin/personas
    moderar_persona.py        #   PATCH …/moderacion
    eliminar_persona.py       #   DELETE …/{person_id}
tests/
  conftest.py          # fixtures: client, policy, admin_token, admin_headers
  domain/
    test_matching.py   # 14 tests, 100% coverage
    test_privacy.py    # 8 tests, 100% coverage
  use_cases/           # ⭐ tests de la capa use_cases (46 tests)
    __init__.py
    test_registrar_busqueda.py
    test_registrar_encontrado.py
    test_buscar_admin.py
    test_listar_personas_admin.py
    test_moderar_persona.py
    test_eliminar_persona.py
  repositories/        # fake in-memory del repo, solo para tests
    __init__.py
    fake.py            #   FakePersonaRepository (test-only)
```

### 3.1 Domain layer (`app/domain/`)

Lógica de negocio **sin SQL ni HTTP**. Tres módulos:

- **`matching.MatchingPolicy`** — fuente única de verdad para:
  - `is_match(distance)` — bool, `distance < threshold` (estricto).
  - `confidence_band(distance)` — `"alta"` / `"media"` / `"baja"`.
  - `match_percentage(distance)` — entero 0–100 vía `faces.distance_to_confidence`
    (sigmoide calibrada para InsightFace buffalo_l: `k=12.0`, `midpoint=0.40`).
  - El umbral operativo se carga de `Settings.match_threshold` (= 0.55) en `lifespan`.
- **`privacy.MenoresPrivacy(obj)`** — única llamada que enmascara `nombre`/`apellido`
  (o `familiar_nombre` en `AlertaFamiliar`) cuando `es_menor=True`. Se aplica en el
  **borde de la respuesta**, sin mutar el objeto original.
- **`persona.PersonaBase`** — entidad de dominio con `Estado` enum (`buscada`/`encontrada`)
  y `Foto` dataclass. Es el modelo interno; las respuestas usan `Candidato` /
  `PersonaAdmin` / `AlertaFamiliar` de `app/schemas.py`.

### 3.2 Repository layer (`app/repositories/`)

Toda la SQL de las tablas `personas` y `persona_embeddings` vive en
`PersonaRepository`. `app/main.py` no contiene SQL de estas tablas. Operaciones:

- `add(person_id, datos, procesadas)` — inserta una fila por foto en `personas` y
  N embeddings por foto en `persona_embeddings` (base + rotaciones ±15°).
- `search_by_estado(embedding, estado, limit)` — búsqueda pública, filtra por
  `moderacion = 'aprobada'`. Usa `ROW_NUMBER() OVER (PARTITION BY p.person_id
  ORDER BY pe.embedding <=> %s ASC)` para devolver el mejor match por persona.
- `search_admin(embedding, estado, limit)` — igual pero **sin** filtro de moderación.
- `list_admin(limit, estado, moderacion)` — agregado por `person_id` con filtros
  opcionales de estado y moderación.
- `set_moderacion(person_id, valor)` — actualiza `moderacion` (commit incluido).
- `delete(person_id)` — borra filas y limpia el almacenamiento (best-effort).

Los métodos de mapeo `_row_to_candidato_dict` / `_row_to_admin_dict` calculan
`coincidencia` y `confianza` a través del `MatchingPolicy` inyectado. **No**
aplican privacidad: `MenoresPrivacy` se invoca en el handler del endpoint.

### 3.3 Use case layer (`app/use_cases/`)

Una clase por flujo de negocio. Los endpoints de `app/main.py` se vuelven
**adaptadores HTTP delgados** (≤20 líneas): parsean form / query / path,
llaman a `use_case.execute(...)`, y devuelven el modelo Pydantic. La
orquestación (validación, construcción de `PersonaBase`, llamadas al repo,
aplicación de `MenoresPrivacy`, ensamblado de la respuesta) vive en el use case.

| Use case | Endpoint | Responsabilidad |
|---|---|---|
| `RegistrarBusqueda` | `POST /buscados` | valida form, arma `PersonaBase` (`estado=BUSCADA`, `moderacion="aprobada"`), `repo.add`, busca en `encontrada`, aplica `MenoresPrivacy` y devuelve `ResultadoBusqueda` |
| `RegistrarEncontrado` | `POST /encontrados` | valida form (4 reglas, incluyendo `es_menor ⇒ doc_responsable` obligatorio), arma `PersonaBase` (`estado=ENCONTRADA`, `moderacion="pendiente"`), `repo.add`, **construye la `AlertaFamiliar` cross-flow** si hay match, aplica `MenoresPrivacy` y devuelve `ResultadoRegistro` |
| `BuscarAdmin` | `POST /buscar` | clamp de `limite`, `repo.search_admin`, aplica `MenoresPrivacy`, devuelve `list[Candidato]` |
| `ListarPersonasAdmin` | `GET /admin/personas` | `repo.list_admin`, aplica `MenoresPrivacy`, devuelve `list[PersonaAdmin]` |
| `ModerarPersona` | `PATCH /admin/personas/{id}/moderacion` | valida `valor ∈ {aprobada, rechazada, pendiente}`, `repo.set_moderacion`, devuelve `{person_id, moderacion, fotos_actualizadas}` |
| `EliminarPersona` | `DELETE /admin/personas/{person_id}` | `repo.delete`, devuelve `{person_id, eliminada, fotos}` |

`admin_login` (`POST /admin/login`) y `GET /health` se quedan **en `app/main.py`**
por decisión explícita (no tocan `PersonaRepository`; extraerlos no aporta).

**Excepciones de dominio.** El módulo `_exceptions.py` define 4 excepciones que
los use cases elevan; el helper `_use_case_execute` en `app/main.py` las mapea
a HTTP en el endpoint:

| Excepción | HTTP |
|---|---|
| `PersonaValidationError` | 422 |
| `RostroNoDetectadoError` | 422 |
| `PersonaNotFoundError` | 404 (mensaje por defecto: *"No existe esa persona"*) |
| `ModificacionInvalidaError` | 400 |

Los use cases **nunca** importan `HTTPException` ni `fastapi`; la capa HTTP
queda afuera del negocio.

**PersonaBase fluye por el sistema.** `PersonaRepository.add(...)` ahora recibe
un `PersonaBase` (modelo Pydantic de `app/domain/persona.py`) en vez de un
`dict[str, Any]`. El repo mapea internamente los campos a los nombres de
parámetro SQL (`persona.es_menor → %(menor)s`, `persona.telefono_contacto →
%(tel_contacto)s`, etc.). Los endpoints ya no construyen el `datos` en español
a mano: lo arma el use case.

**Testeable sin InsightFace ni PostgreSQL.** `tests/repositories/fake.py`
provee `FakePersonaRepository`, una implementación in-memory que respeta la
misma interfaz pública que el repo real (`add`, `search_by_estado`,
`search_admin`, `list_admin`, `set_moderacion`, `delete`). Es **solo** para
tests — el código de `app/` no la importa. La cobertura de
`app/use_cases/` es **100%** y los tests corren en milisegundos.

---

## 4. Flujos de datos

Hay **dos flujos** que se cruzan cuando hay match, más los endpoints de **admin**.
El sistema prioriza la **protección de menores** y la **moderación** antes de
exponer cualquier coincidencia públicamente.

> Los pasos que siguen describen la orquestación completa, que vive en la clase
> del use case correspondiente (ver §3.3). El endpoint HTTP solo parsea el
> request, llama a `use_case.execute(...)` y devuelve el modelo Pydantic.

### 4.1 FAMILIAR — `POST /buscados`

1. Llega la(s) foto(s) (multipart).
2. InsightFace buffalo_l decodifica y reescala a ≤1000 px.
3. Por cada foto: extrae **1 embedding base + hasta 2 augmentaciones** (rotaciones
   ±15°). Las augmentaciones donde no se detecta rostro se omiten.
4. Cada imagen se sube a **Spaces** (o `/data/fotos` local) → URL pública.
5. Se inserta en `personas` (1 fila por foto) y `persona_embeddings` (N filas por
   foto). `estado = 'buscada'`.
6. Búsqueda: `search_by_estado(embedding, "encontrada", limite)` con
   `moderacion = 'aprobada'`. Cada candidato pasa por `MenoresPrivacy`.
7. Se devuelve `ResultadoBusqueda { codigo, total, coincidencias }`.

### 4.2 RESCATISTA — `POST /encontrados`

1. Mismo pipeline de fotos y embeddings.
2. `estado = 'encontrada'`. **Datos de menor se almacenan tal cual** (no se nulean
   en BD); el enmascaramiento ocurre al serializar la respuesta.
3. Búsqueda: `search_by_estado(embedding, "buscada", 1)`.
4. Si el mejor match pasa `MatchingPolicy.is_match(d)` se construye
   `AlertaFamiliar` y se aplica `MenoresPrivacy` antes de devolverlo.
5. Se devuelve `ResultadoRegistro { codigo, person_id, alerta }`.

### 4.3 ADMIN — `POST /buscar`, `GET /admin/personas`, `PATCH …/moderacion`, `DELETE`

- Requieren header `Authorization: Bearer <jwt>` validado por
  `get_current_admin` (bcrypt + JWT firmado HS256).
- `POST /buscar` usa `search_admin` (sin filtro de moderación). Pasa cada
  candidato por `MenoresPrivacy` (Q1 revisado: el admin regular ve nombres
  enmascarados para menores).
- `GET /admin/personas` usa `list_admin` con filtros opcionales de `estado` y
  `moderacion`. También aplica `MenoresPrivacy`.
- `PATCH /admin/personas/{id}/moderacion?valor=aprobada|rechazada|pendiente`
  actualiza el estado. Solo aparecen en búsquedas públicas las `aprobada`.
- `DELETE /admin/personas/{id}` borra la persona, las filas de
  `persona_embeddings` (cascade) y limpia las imágenes del storage.

---

## 5. Modelo de reconocimiento (decisión por evidencia)

| Pieza | Valor | Origen |
|---|---|---|
| **Modelo** | InsightFace **buffalo_l** (ArcFace w600k_r50) | `evaluate.py` (comparativa) |
| **Detector** | **RetinaFace** | incluido en buffalo_l |
| **Dim embedding** | 512 | `Settings.embedding_dim` |
| **Augmentaciones por foto** | base + rotaciones ±15° | `faces.embeddings_from_bytes` |
| **Distancia** | coseno (`<=>` operador de pgvector) | `normed_embedding` L2-normalizado |
| **Umbral de match** | **0.55** | `Settings.match_threshold` |
| **% coincidencia** | sigmoide (`k=12.0`, `midpoint=0.40`) | `faces.distance_to_confidence` |
| **Bandas de confianza** | alta `< 0.40` · media `< 0.55` · baja | `MatchingPolicy` |

> El divisor `1.2` (era Facenet512) está **eliminado**. El cálculo actual es la
> sigmoide calibrada para InsightFace buffalo_l. Valores típicos:
>
> - distancia 0.10 → ~97% (match muy claro)
> - distancia 0.25 → ~85% (match sólido)
> - distancia 0.40 → ~50% (punto de incertidumbre)
> - distancia 0.55 → ~16% (en el umbral — revisar manualmente)

### 5.1 Privacidad de menores

`MenoresPrivacy` es la **única** llamada que enmascara datos de menores y se
aplica a **todas** las respuestas regulares (públicas y admin):

| Endpoint | Aplica privacidad | Fuente |
|---|---|---|
| `POST /buscados` (FAMILIAR) | sí | `MenoresPrivacy(Candidato)` en `RegistrarBusqueda.execute()` |
| `POST /encontrados` (RESCATISTA) | sí — `AlertaFamiliar.familiar_nombre` | `MenoresPrivacy(AlertaFamiliar)` en `RegistrarEncontrado.execute()` |
| `POST /buscar` (ADMIN) | sí | `MenoresPrivacy(Candidato)` en `BuscarAdmin.execute()` |
| `GET /admin/personas` (ADMIN) | sí | `MenoresPrivacy(PersonaAdmin)` en `ListarPersonasAdmin.execute()` |

Los nombres reales de menores **sí se guardan** en la BD; el control se hace
por acceso (quién tiene cuenta admin activa) y por enmascaramiento en serialización.
El endpoint "super-admin con rol" que bypasea la máscara queda **fuera de alcance**
de este change (deferido).

### 5.2 Moderación

Columna `moderacion` en `personas` con valores `aprobada` (defecto, visible) /
`rechazada` (oculta) / `pendiente` (a revisar). Las **búsquedas públicas filtran
siempre por `aprobada`**. El admin puede listar por cualquier estado y cambiarlo
desde `PATCH /admin/personas/{id}/moderacion`.

---

## 6. Auth de admin

- **Passwords** se guardan con **bcrypt** (passlib) en la tabla `admins`. Nunca en plano.
- **Login**: `POST /admin/login` valida contra BD y devuelve un **JWT firmado
  HS256** (`sub`=admin_id, `username`, `iat`, `exp`). Expiración configurable
  (`JWT_EXPIRES_MINUTES`, defecto 60 min).
- **Guard**: `get_current_admin` decodifica el JWT, carga el admin por `sub` y
  verifica `is_active`. Devuelve 401 si token falta/está mal/expiró, 403 si
  `is_active=false`.
- **Bootstrap**: la primera vez que se levanta el servicio con `ADMIN_USER` /
  `ADMIN_PASSWORD` en `.env`, se siembra el admin automáticamente. Luego esos
  env vars se ignoran — el login siempre valida contra BD.
- **Gestión**: `python -m app.cli {create-admin,change-password,deactivate-admin,activate-admin,list-admins}`.
  `JWT_SECRET` es **obligatorio** en producción (el server falla al primer
  intento de login si está vacío).

---

## 7. Infraestructura

- **Droplet** DigitalOcean (Ubuntu 24.04) en `137.184.107.94`.
  - Disco de boot pequeño (~10 GB) → **todo lo pesado vive en un volumen de 20 GB**
    (`/mnt/volumen1`): código, venv, pesos de InsightFace y **datos de Postgres**.
- **nginx** sirve también `unimetlabs.lat` (otra app) — no tocar.
- **pm2** gestiona el proceso `rostros-api` (auto-restart, logs en el volumen).
- **SSL** por Certbot (Let's Encrypt) para `symtechven.com`.
- **docker-compose** (ver `DOCKER.md`): `api` + `pgvector/pgvector:pg16`.
- **`Dockerfile.standalone`** + `docker/standalone/*` para empaquetado single-image.

### Particularidades técnicas (lecciones aprendidas)

- `app.database` (psycopg) se importa **antes** que `app.faces` (TensorFlow) para
  evitar un crash nativo `free(): invalid pointer`.
- **No** se usa índice `ivfflat` (con pocos registros omite filas y devuelve vacío);
  se usa **HNSW**, correcto con pocos o muchos registros.
- Los datos de Postgres se movieron al volumen porque el disco de boot se llenaba.
- `init_db()` toma un `pg_advisory_lock` para que varios workers no choquen al
  crear la extensión/tabla a la vez. La columna `personas.embedding` (Facenet512)
  y su índice HNSW se eliminan al migrar a InsightFace; los datos viejos se
  recrean re-registrando.
- `INSIGHTFACE_HOME` permite apuntar el cache de pesos (~300 MB) a un volumen
  persistente y evitar re-descargas en cada deploy.

---

## 8. Escalabilidad

| Eje | Estado | Nota |
|---|---|---|
| Imágenes | ✅ Ilimitado | Spaces |
| Vectores | ✅ A millones | pgvector + HNSW |
| Búsqueda | ✅ Rápida a escala | índice HNSW, `ROW_NUMBER() OVER (PARTITION BY ...)` |
| **Procesar caras (CPU)** | ⚠️ Cuello de botella | ~6 s/imagen en CPU; concurrencia limitada por nº de vCPU |
| **Concurrencia** | ⚠️ CPU-bound | más vCPUs + más workers de uvicorn |

- **Latencia** por búsqueda: ~6 s (inferencia de RetinaFace en CPU). Aceptable
  para el caso de uso (no es tiempo real).
- **Concurrencia**: se escala con **más vCPUs** + más *workers* de uvicorn
  (no con GPU en DigitalOcean, que solo ofrece H100 ~$2.5k/mes).
- Para carga muy alta sostenida: GPU en proveedor externo (RunPod/Lambda) + cola
  de trabajos; la arquitectura es stateless y ya está preparada.

---

## 9. Endpoints

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `GET` | `/health` | — | Estado del servicio |
| `POST` | `/buscados` | — | **FAMILIAR**: registra búsqueda y devuelve encontrados similares |
| `POST` | `/encontrados` | — | **RESCATISTA**: registra persona encontrada y emite alerta si hay match |
| `POST` | `/admin/login` | — | Login. Devuelve JWT firmado (HS256) |
| `POST` | `/buscar` | Bearer | **ADMIN**: comparar una foto contra TODA la base (sin filtro de moderación) |
| `GET` | `/admin/personas` | Bearer | **ADMIN**: listar registros (filtros `estado`, `moderacion`) |
| `PATCH` | `/admin/personas/{id}/moderacion` | Bearer | **ADMIN**: aprobar / rechazar / marcar pendiente |
| `DELETE` | `/admin/personas/{id}` | Bearer | **ADMIN**: borrar (limpia storage) |

Errores frecuentes en endpoints protegidos:

| Código | Cuándo |
|---|---|
| `401` | Sin `Authorization`, token mal firmado, expirado, o admin inexistente |
| `403` | Admin con `is_active=false` (cuenta desactivada) |

Documentación interactiva: **`/api/docs`** (Swagger) y **`/api/redoc`** (ReDoc).
Detalle de los campos en `API.md`.

---

## 10. Modelo de datos (Postgres + pgvector)

### `personas`

Una fila por **foto**. Varias fotos de la misma persona comparten `person_id`.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | UUID PK | id de la foto |
| `person_id` | UUID | agrupa fotos de la misma persona |
| `estado` | TEXT | `'buscada'` \| `'encontrada'` (defecto `'buscada'`) |
| `es_menor` | BOOL | activa el protocolo de privacidad al serializar |
| `nombre`, `apellido`, `edad` | TEXT NULL | se guardan **siempre** (incluso para menores) |
| `doc_tipo`, `doc_numero` | TEXT NULL | identificación |
| `telefono_contacto` | TEXT NULL | familiar |
| `refugio`, `ubicacion` | TEXT NULL | dónde se encuentra / fue hallada |
| `telefono_responsable`, `doc_responsable` | TEXT NULL | obligado si `es_menor=true` |
| `descripcion` | TEXT NULL | descripción física |
| `codigo` | TEXT NULL | `REE-XXXXXXXX` |
| `moderacion` | TEXT | `'aprobada'` (defecto) \| `'rechazada'` \| `'pendiente'` |
| `image_url`, `image_key` | TEXT | Spaces o `/fotos/...` local |
| `created_at` | TIMESTAMPTZ | |

### `persona_embeddings`

N vectores por foto (1 base + hasta 2 augmentaciones ±15°).

| Columna | Tipo | Notas |
|---|---|---|
| `id` | UUID PK | default `gen_random_uuid()` |
| `foto_id` | UUID FK → `personas.id` ON DELETE CASCADE | |
| `embedding` | `vector(512)` | L2-normalizado (coseno = 1 - dot product) |
| `calidad_rostro` | FLOAT | `det_score` de InsightFace (0–1) |
| `created_at` | TIMESTAMPTZ | |

Índices: HNSW sobre `embedding` con `vector_cosine_ops`, BTREE sobre `foto_id`.

### `admins`

Cuentas de superadmin. El password **nunca** en plano: vive como hash bcrypt.

| Columna | Tipo | Notas |
|---|---|---|
| `id` | UUID PK | default `gen_random_uuid()` |
| `username` | TEXT UNIQUE | |
| `password_hash` | TEXT | bcrypt (`passlib`) |
| `is_active` | BOOL | defecto `true` |
| `created_at`, `last_login_at` | TIMESTAMPTZ | |

---

## 11. Estructura del repositorio

```
app/
  main.py              # FastAPI: endpoints + lifespan + acceso a policy/repo
  config.py            # pydantic-settings Settings class
  database.py          # psycopg pool, init_db, pgvector, HNSW, tabla admins
  faces.py             # InsightFace buffalo_l (detección + embedding + warmup)
  storage.py           # boto3 (Spaces) con fallback a /data/fotos local
  auth.py              # JWT + bcrypt + guard get_current_admin
  cli.py               # gestión de admins
  schemas.py           # Pydantic: LoginBody, Candidato, AlertaFamiliar, …
  domain/              # lógica de dominio pura
    matching.py
    privacy.py
    persona.py
  repositories/        # toda la SQL de personas / persona_embeddings
    persona.py
  use_cases/           # ⭐ una clase por flujo de negocio (ver §3.3)
    __init__.py        #   barrel
    _exceptions.py     #   excepciones de dominio
    _helpers.py        #   LIMITE_MAX, _gen_codigo, _embedding_consulta
    registrar_busqueda.py
    registrar_encontrado.py
    buscar_admin.py
    listar_personas_admin.py
    moderar_persona.py
    eliminar_persona.py
frontend/
  index.html           # SPA single-file (3 pestañas)
tests/
  conftest.py          # fixtures
  domain/
    test_matching.py   # 14 tests
    test_privacy.py    # 8 tests
  use_cases/           # ⭐ 46 tests sobre la capa de use cases
    __init__.py
    test_registrar_busqueda.py
    test_registrar_encontrado.py
    test_buscar_admin.py
    test_listar_personas_admin.py
    test_moderar_persona.py
    test_eliminar_persona.py
  repositories/        # fake in-memory del repo (test-only)
    __init__.py
    fake.py
openspec/
  changes/             # cambios activos + change artifacts
    use-case/          # change vigente (próximo a archivar)
      proposal.md
      specs/use-case/spec.md
      design.md
      tasks.md
      verify-report.md
      apply-progress.md
      sync-report.md
  specs/               # ⭐ specs canónicas (sync target)
    core-domain/spec.md
    use-case/spec.md
  config.yaml          # configuración del flujo SDD
evaluate.py            # benchmark 5 modelos × 3 detectores
benchmark_lfw.py       # benchmark LFW
benchmark_dlib.py      # comparación dlib/face-api.js
Dockerfile             # imagen multi-stage
Dockerfile.standalone  # imagen single-image (docker/standalone/*)
docker-compose.yml
requirements.txt       # runtime + dev (pytest, httpx, pytest-asyncio)
.env.example
API.md                 # contrato HTTP
DEPLOY.md              # despliegue en droplet
DOCKER.md              # build/run con docker-compose
ARQUITECTURA.md        # este documento
CLAUDE.md / AGENTS.md  # guía para colaboradores
```

---

## 12. Tests

- **Runner**: `pytest` (no strict TDD; tests junto al código).
- **Cobertura**:
  - `app/domain/` — **100%** (62/62 statements) — preservado.
  - `app/use_cases/` — **100%** (136/136 statements en las 6 clases + helpers +
    exceptions + barrel).
  - `app/repositories/` — 28% (cubre el fake; tests de integración con
    PostgreSQL + pgvector reales diferidos).
- **Tests acumulados** (68 totales):
  - `tests/domain/test_matching.py` — 14 tests (umbral, bandas, sigmoide).
  - `tests/domain/test_privacy.py` — 8 tests (mask Candidato, PersonaAdmin, AlertaFamiliar).
  - `tests/use_cases/test_registrar_busqueda.py` — 13 tests (FAMILIAR).
  - `tests/use_cases/test_registrar_encontrado.py` — 12 tests (RESCATISTA + alerta).
  - `tests/use_cases/test_buscar_admin.py` — 5 tests (admin search).
  - `tests/use_cases/test_listar_personas_admin.py` — 6 tests (admin list).
  - `tests/use_cases/test_moderar_persona.py` — 6 tests (moderación).
  - `tests/use_cases/test_eliminar_persona.py` — 4 tests (delete).
- **Fake in-memory** en `tests/repositories/fake.py` (`FakePersonaRepository`):
  implementa la misma interfaz pública que el repo real. **Test-only**;
  el código de `app/` nunca la importa. Permite que los use-case tests
  corran en milisegundos, sin InsightFace ni PostgreSQL.
- **Fixtures clave** en `tests/conftest.py`:
  - `client` (TestClient de FastAPI, sin levantar lifespan).
  - `policy` (MatchingPolicy con `threshold=0.55`).
  - `admin_token` / `admin_headers` (Bearer token para endpoints de admin).
- **Gap conocido**: tests de integración del `PersonaRepository` real
  requieren PostgreSQL + pgvector corriendo; diferido a un cambio futuro.
