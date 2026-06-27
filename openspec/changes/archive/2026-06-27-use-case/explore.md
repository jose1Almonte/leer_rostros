Since file-write tools and intercom are unavailable, I will return the full exploration document inline. The parent can persist it to `openspec/changes/use-case/explore.md`.

---

## SDD Explore — `use-case` Change

**Project**: reencuentros  
**Change**: use-case  
**Phase**: sdd-explore  
**Date**: 2026-06-27  
**Status**: complete  

---

### 0. Executive Summary

`app/main.py` (515 lines) still contains inline orchestration for all 8 endpoints: validation, `datos` dict construction, repository calls, `MenoresPrivacy` application, cross-flow alert construction, and response shaping. This phase maps each endpoint line-by-line to define what moves into use case modules and what stays as thin HTTP adapters. The key deepening beyond `core-domain` is refactoring `PersonaRepository.add` to accept `PersonaBase` (domain object) instead of a raw `dict`, and making endpoints dependency-injection-friendly by passing `repo` and `policy` explicitly.

---

### 1. Current State of Each Endpoint

#### 1.1 `GET /health` — `health`
- **Current shape**: `app/main.py:251-252` (2 lines)
- **Business logic inline**: None — returns `{"status": "ok"}`
- **What stays in endpoint**: Everything (already minimal)
- **What moves to use case**: Nothing
- **Proposed use case method signature**: N/A
- **Lines saved in main.py**: 0 (already thin)

#### 1.2 `POST /admin/login` — `admin_login`
- **Current shape**: `app/main.py:273-280` (but in the current file it's around lines 270-290; actual: lines after the docstring ~270-290). In the current file read, lines ~248-270. ~22 lines
- **Business logic inline**:
  - Inline SQL SELECT from `admins` table (`app/main.py:255-258`)
  - bcrypt password verification via `verify_password`
  - `touch_last_login` call
  - JWT creation via `create_access_token`
  - HTTP 401 on failure
- **What stays in endpoint**: JSON body parsing (`LoginBody`), HTTPException mapping, response wrapping (`LoginResp`)
- **What moves to use case** (if extracted):
  - DB query for admin by username
  - Password verification
  - Update `last_login_at`
  - JWT token creation
- **Proposed use case method signature**:
  ```python
  class AdminLogin:
      def __init__(self, pool: ConnectionPool): ...
      def execute(self, username: str, password: str) -> str:  # returns JWT token
          # raises AuthenticationError (domain exception) → endpoint maps to 401
  ```
- **Lines saved in main.py**: ~18 → ~4 (thin adapter)
- **Special note**: This is the only endpoint that does NOT touch `PersonaRepository`. It touches the `admins` table. See section 5.

#### 1.3 `POST /buscados` — `registrar_busqueda` (FAMILIAR)
- **Current shape**: `app/main.py:289-345` (async endpoint with many form params). In current file: lines ~278-334. ~56 lines
- **Business logic inline**:
  - `await _procesar_fotos(files)` → `procesadas` (face processing)
  - Validation: `if not procesadas: raise 422`
  - Validation: `if not (doc_numero or (nombre and nombre.strip())): raise 422`
  - `limite` clamping: `max(1, min(LIMITE_MAX, limite))`
  - `_embedding_consulta(procesadas)` → base embedding
  - `person_id = uuid.uuid4()`, `codigo = gen_codigo()`
  - `datos` dict construction (16 keys, Spanish SQL parameter names)
  - `repo.add(person_id, datos, procesadas)`
  - `repo.search_by_estado(embedding, "encontrada", limite)` → `encontrados`
  - `candidatos = [MenoresPrivacy(Candidato(**d)) for d in encontrados]`
  - `ResultadoBusqueda(codigo, total, coincidencias)` response
- **What stays in endpoint**:
  - Form parameter declaration (`UploadFile`, `Form` fields)
  - Call to `_procesar_fotos` (face processing stays at HTTP boundary)
  - HTTPException mapping
  - Response model construction (`ResultadoBusqueda`)
- **What moves to use case**:
  - Validation rules (at least name or doc; procesadas not empty)
  - `limite` clamping
  - `person_id` + `codigo` generation
  - `PersonaBase` construction from form fields
  - `repo.add(person_id, persona_base, procesadas)` (after repo refactor)
  - `repo.search_by_estado(embedding, "encontrada", limite)`
  - `MenoresPrivacy` application
  - `ResultadoBusqueda` data assembly (codigo, total, candidatos)
- **Proposed use case method signature**:
  ```python
  class RegistrarBusqueda:
      def __init__(self, repo: PersonaRepository, policy: MatchingPolicy): ...
      def execute(
          self,
          procesadas: list[ProcessedPhoto],
          nombre: str | None,
          apellido: str | None,
          edad: str | None,
          doc_tipo: str | None,
          doc_numero: str | None,
          telefono_contacto: str | None,
          limite: int,
      ) -> ResultadoBusqueda:
          # raises PersonaValidationError → endpoint maps to 422
  ```
- **Lines saved in main.py**: ~56 → ~10 (thin adapter)

#### 1.4 `POST /encontrados` — `registrar_encontrado` (RESCATISTA)
- **Current shape**: `app/main.py:347-410` (current file: ~336-402). ~66 lines
- **Business logic inline**:
  - `await _procesar_fotos(files)`
  - Validation: procesadas not empty
  - Validation: `refugio` required
  - Validation: `telefono_responsable` required
  - Validation: if `es_menor`, `doc_responsable` required
  - `embedding = _embedding_consulta(procesadas)`
  - `person_id = uuid.uuid4()`, `codigo = gen_codigo()`
  - `datos` dict construction (16 keys)
  - `repo.add(person_id, datos, procesadas)`
  - `buscados = repo.search_by_estado(embedding, "buscada", 1)`
  - Cross-flow alert construction:
    - `if buscados: best = buscados[0]; d = best["distancia"]`
    - `if get_policy().is_match(d):` → build `AlertaFamiliar`
    - `alerta = MenoresPrivacy(alerta)`
  - `ResultadoRegistro(codigo, person_id, alerta)` response
- **What stays in endpoint**:
  - Form parameter declaration
  - `_procesar_fotos` call
  - HTTPException mapping
  - Response model construction
- **What moves to use case**:
  - All 4 validations
  - `person_id`, `codigo` generation
  - `PersonaBase` construction
  - `repo.add`
  - `repo.search_by_estado(embedding, "buscada", 1)`
  - Cross-flow alert construction (policy.is_match + AlertaFamiliar + MenoresPrivacy)
  - `ResultadoRegistro` assembly
- **Proposed use case method signature**:
  ```python
  class RegistrarEncontrado:
      def __init__(self, repo: PersonaRepository, policy: MatchingPolicy): ...
      def execute(
          self,
          procesadas: list[ProcessedPhoto],
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
          # raises PersonaValidationError → 422
  ```
- **Lines saved in main.py**: ~66 → ~12

#### 1.5 `POST /buscar` — `buscar_admin` (ADMIN)
- **Current shape**: `app/main.py:412-441` (current file: ~404-433). ~29 lines
- **Business logic inline**:
  - `data = await file.read()`
  - `faces.embedding_from_bytes(data)` → embedding (single photo, no augmentation)
  - `limite` clamping
  - `repo.search_admin(embedding, estado, limite)`
  - `MenoresPrivacy(Candidato(**d))` application
  - Return list of `Candidato`
- **What stays in endpoint**:
  - `UploadFile` parameter
  - `faces.embedding_from_bytes` call (face processing at boundary)
  - HTTPException on ValueError from faces
  - Auth dependency (`Depends(get_current_admin)`)
- **What moves to use case**:
  - `limite` clamping
  - `repo.search_admin(embedding, estado, limite)`
  - `MenoresPrivacy` application
- **Proposed use case method signature**:
  ```python
  class BuscarAdmin:
      def __init__(self, repo: PersonaRepository, policy: MatchingPolicy): ...
      def execute(self, embedding: Any, estado: str | None, limite: int) -> list[Candidato]: ...
  ```
- **Lines saved in main.py**: ~29 → ~8

#### 1.6 `GET /admin/personas` — `listar` (ADMIN)
- **Current shape**: `app/main.py:443-463` (current file: ~435-455). ~20 lines
- **Business logic inline**:
  - `repo.list_admin(limite, estado, moderacion)`
  - `MenoresPrivacy(PersonaAdmin(**d))` application
  - Return list of `PersonaAdmin`
- **What stays in endpoint**:
  - Query param parsing
  - Auth dependency
- **What moves to use case**:
  - `repo.list_admin(...)`
  - `MenoresPrivacy` application
- **Proposed use case method signature**:
  ```python
  class ListarPersonasAdmin:
      def __init__(self, repo: PersonaRepository): ...
      def execute(self, limite: int, estado: str | None, moderacion: str | None) -> list[PersonaAdmin]: ...
  ```
- **Lines saved in main.py**: ~20 → ~5

#### 1.7 `PATCH /admin/personas/{person_id}/moderacion` — `moderar` (ADMIN)
- **Current shape**: `app/main.py:465-485` (current file: ~457-477). ~20 lines
- **Business logic inline**:
  - Validation: `valor in ("aprobada", "rechazada", "pendiente")`
  - `repo.set_moderacion(person_id, valor)`
  - 404 if `n == 0`
  - Return dict response
- **What stays in endpoint**:
  - Path param + query param parsing
  - Auth dependency
  - HTTPException mapping
- **What moves to use case**:
  - Validation of `valor`
  - `repo.set_moderacion`
  - 404 check logic
- **Proposed use case method signature**:
  ```python
  class ModerarPersona:
      def __init__(self, repo: PersonaRepository): ...
      def execute(self, person_id: str, valor: str) -> dict:  # {person_id, moderacion, fotos_actualizadas}
          # raises ModeracionValidationError → 400
          # raises PersonaNotFoundError → 404
  ```
- **Lines saved in main.py**: ~20 → ~6

#### 1.8 `DELETE /admin/personas/{person_id}` — `eliminar` (ADMIN)
- **Current shape**: `app/main.py:487-505` (current file: ~479-497). ~18 lines
- **Business logic inline**:
  - `repo.delete(person_id)`
  - 404 if `fotos == 0`
  - Return dict response
- **What stays in endpoint**:
  - Path param parsing
  - Auth dependency
  - HTTPException mapping
- **What moves to use case**:
  - `repo.delete`
  - 404 check logic
- **Proposed use case method signature**:
  ```python
  class EliminarPersona:
      def __init__(self, repo: PersonaRepository): ...
      def execute(self, person_id: str) -> dict:  # {person_id, eliminada, fotos}
          # raises PersonaNotFoundError → 404
  ```
- **Lines saved in main.py**: ~18 → ~5

---

### 2. Current State of `PersonaRepository.add`

#### 2.1 Current shape
- **File**: `app/repositories/persona.py:112-136`
- **Signature**: `add(self, person_id: UUID, datos: dict[str, Any], procesadas: list[tuple[bytes, str, list[tuple[Any, float]]]]) -> list[str]`
- **The `datos` dict**: Built inline in each endpoint with Spanish keys that match SQL parameter placeholders:
  ```python
  datos = {
      "estado": "buscada",      # → %(estado)s
      "menor": False,           # → %(menor)s  (maps to es_menor column)
      "nombre": nombre,
      "apellido": apellido,
      "edad": edad,
      "doc_tipo": doc_tipo,
      "doc_numero": doc_numero,
      "tel_contacto": telefono_contacto,  # → telefono_contacto column
      "refugio": refugio,
      "tel_resp": telefono_responsable,   # → telefono_responsable column
      "doc_resp": doc_responsable,        # → doc_responsable column
      "descripcion": descripcion,
      "ubicacion": ubicacion,
      "codigo": codigo,
  }
  ```
  The repository spreads `datos` into the SQL params dict plus `id`, `pid`, `url`, `key`.

#### 2.2 Proposed shape
```python
def add(
    self,
    person_id: UUID,
    persona: PersonaBase,
    procesadas: list[ProcessedPhoto],
) -> list[str]:
```

Where:
- **`PersonaBase`** is the existing Pydantic model from `app/domain/persona.py` (lines 23-49)
- **`ProcessedPhoto`** is a new dataclass:
  ```python
  @dataclass
  class ProcessedPhoto:
      data: bytes
      content_type: str
      embeddings: list[tuple[np.ndarray, float]]  # (embedding, calidad)
  ```

#### 2.3 Implications
- The endpoint's `datos` dict disappears entirely. The use case builds a `PersonaBase` from form fields.
- The repository maps `PersonaBase` fields to SQL parameters internally (e.g., `persona.es_menor` → `menor` param, `persona.telefono_contacto` → `tel_contacto` param).
- `Estado` enum validation happens naturally via `PersonaBase.estado: Estado` (Pydantic validates).
- The repository becomes the only place that knows the SQL parameter naming convention.
- Both `registrar_busqueda` and `registrar_encontrado` use cases construct `PersonaBase` differently (different fields populated) but pass the same type to the repo.

---

### 3. New Module Structure

**Proposed structure: one file per use case** (preferred for clarity and reviewability):

```
app/
  use_cases/
    __init__.py              # Barrel — exports all use case classes
    registrar_busqueda.py    # RegistrarBusqueda
    registrar_encontrado.py  # RegistrarEncontrado
    buscar_admin.py          # BuscarAdmin
    listar_personas_admin.py # ListarPersonasAdmin
    moderar_persona.py       # ModerarPersona
    eliminar_persona.py      # EliminarPersona
```

**Alternative: grouped by flow**:
```
app/
  use_cases/
    __init__.py
    personas.py              # RegistrarBusqueda, RegistrarEncontrado, BuscarAdmin, ListarPersonasAdmin, ModerarPersona, EliminarPersona
```

**Rationale for one-file-per-use-case**:
- Each use case is independently testable.
- Clear mapping from endpoint to file (makes navigation easy).
- Review budget is 800 lines; 7 small files (~20-40 lines each) are easier to review than one 200-line file.
- No strong coupling between the use cases (each is a distinct flow).
- Consistent with the domain layer pattern (`matching.py`, `privacy.py`, `persona.py` each do one thing).

**`admin_login` special case**:
- Option A: Keep in `app/main.py` (it's only ~22 lines, touches `admins` table not `PersonaRepository`).
- Option B: Move to `app/use_cases/admin_login.py` for consistency.
- Option C: Move to `app/auth.py` since it's auth-related.
- **Recommendation**: Option B (`app/use_cases/admin_login.py`) for consistency, but it's low priority. The endpoint is already thin. See open questions.

---

### 4. Test Strategy for the Use Case Module

#### 4.1 In-memory fake for `PersonaRepository`
- **Location**: `tests/_fakes.py` (test-only, not shipped in `app/`)
- **Rationale**: The fake is test infrastructure, not public API. Keeping it in `tests/` avoids polluting the application package.
- **Shape**:
  ```python
  class FakePersonaRepository:
      def __init__(self, policy: MatchingPolicy):
          self._store: list[PersonaBase] = []
          self._embeddings: list[tuple[UUID, np.ndarray, float]] = []
          self._policy = policy

      def add(self, person_id, persona, procesadas) -> list[str]: ...
      def search_by_estado(self, embedding, estado, limit) -> list[dict]: ...
      def search_admin(self, embedding, estado, limit) -> list[dict]: ...
      def list_admin(self, limit, estado, moderacion) -> list[dict]: ...
      def set_moderacion(self, person_id, valor) -> int: ...
      def delete(self, person_id) -> int: ...
  ```

#### 4.2 What tests cover (per use case)

| Use case | Happy path | Edge cases |
|----------|-----------|------------|
| `RegistrarBusqueda` | Valid form → repo.add + search → returns ResultadoBusqueda | No photos (422), no name/doc (422), limite clamped, no matches |
| `RegistrarEncontrado` | Valid form → repo.add + search → returns ResultadoRegistro with alerta | No photos (422), missing refugio (422), missing tel_responsable (422), es_menor without doc_responsable (422), no cross-match |
| `BuscarAdmin` | Embedding + search → list[Candidato] | Invalid estado, limite clamped |
| `ListarPersonasAdmin` | List with filters → list[PersonaAdmin] | Empty list, filter by estado/moderacion |
| `ModerarPersona` | Valid valor → repo.set_moderacion → success | Invalid valor (400), non-existent person_id (404) |
| `EliminarPersona` | Valid person_id → repo.delete → success | Non-existent person_id (404) |

#### 4.3 Mocking `FaceEmbedder`
- Use cases do NOT call `faces.embeddings_from_bytes` directly.
- The endpoint calls `_procesar_fotos` and passes `procesadas` (or `embedding` for admin search) to the use case.
- Use case tests inject a `FakePersonaRepository` and never touch InsightFace.
- The only policy interaction is `MatchingPolicy.is_match` and `match_percentage` — these are pure and fast.

#### 4.4 Integration tests with FastAPI TestClient
- **Yes**, in addition to use case unit tests.
- Use the existing `client` fixture from `tests/conftest.py` (already overrides `get_current_admin`).
- Integration tests verify:
  - HTTP routing and auth gates
  - Form/file parsing
  - Response model serialization
  - 401/403 on missing/invalid tokens
- Integration tests can mock the use case layer (or the repo layer) to avoid needing a real DB.

---

### 5. Cross-cutting Findings

#### 5.1 `admin_login` — where should it live?
- It is the only endpoint that does NOT use `PersonaRepository`.
- It uses the `admins` table, `verify_password`, `create_access_token`, and `touch_last_login`.
- **Finding**: Keeping it in `app/main.py` is acceptable (it's already thin). Extracting it to a use case is optional and mainly for consistency. If extracted, it should receive `ConnectionPool` (or an `AdminRepository` abstraction) as a dependency.
- **Recommendation**: Document both options in the proposal; default to keeping it in `main.py` unless consistency is strongly preferred.

#### 5.2 `_procesar_fotos` — face processing boundary
- This helper calls `faces.embeddings_from_bytes(data)` which loads InsightFace/TensorFlow.
- **Finding**: Face processing is tightly coupled to InsightFace. The use case should NOT call face processing directly.
- **Recommendation**: The endpoint keeps `_procesar_fotos` and `_embedding_consulta`. It passes `procesadas: list[ProcessedPhoto]` to registration use cases, and `embedding: np.ndarray` to search use cases. This keeps the face-processing seam at the HTTP boundary.

#### 5.3 `get_policy()` and `get_repo()` — global accessors
- These are module-level globals set in `lifespan`. They raise `RuntimeError` if called before initialization.
- **Finding**: This is a testing smell. Use case unit tests cannot easily inject fakes because `get_repo()` returns the real repository.
- **Recommendation**: The use case classes receive `repo: PersonaRepository` and `policy: MatchingPolicy` as constructor arguments. The endpoint can still call `get_repo()` and `get_policy()` to obtain the singletons, but the use case itself is decoupled. This enables testing with fakes.

#### 5.4 Cross-flow alert construction
- In `registrar_encontrado`, after `repo.add`, the code searches for `buscada` matches and constructs an `AlertaFamiliar` if `policy.is_match(d)`.
- **Finding**: This is part of the "register an encontrado" use case (it's what the user expects when they register a found person). However, it's also the natural home for a future `CrossMatch` module (Change C).
- **Recommendation**: Include alert construction in `RegistrarEncontrado` use case for this change. A future `cross-match` change can extract it to a `CrossMatcher` service that `RegistrarEncontrado` calls.

#### 5.5 `MenoresPrivacy` application
- Applied 4 times in `app/main.py`:
  1. `registrar_busqueda` (line ~253 in old file; line ~330 in current): `[MenoresPrivacy(Candidato(**d)) for d in encontrados]`
  2. `registrar_encontrado` (line ~321): `alerta = MenoresPrivacy(alerta)`
  3. `buscar_admin` (line ~359): `[MenoresPrivacy(Candidato(**d)) for d in results]`
  4. `listar` (line ~370): `[MenoresPrivacy(PersonaAdmin(**d)) for d in results]`
- **Finding**: The privacy application is repeated boilerplate. The use case should apply it once before returning results.
- **Recommendation**: Each use case that returns persona data calls `MenoresPrivacy` on the results before returning. The endpoint does not apply privacy.

---

### 6. Specific Code Patterns to Extract

#### 6.1 `registrar_busqueda` (`app/main.py:278-334`)
**Extract to `RegistrarBusqueda.execute`:**
```python
# --- Validations ---
if not procesadas:
    raise HTTPException(422, "No se detectó ningún rostro en la(s) foto(s).")
if not (doc_numero or (nombre and nombre.strip())):
    raise HTTPException(422, "Indica al menos el nombre o el número de identificación.")
limite = max(1, min(LIMITE_MAX, limite))

# --- Domain assembly ---
person_id = uuid.uuid4()
codigo = gen_codigo()
datos = { ... }  # → PersonaBase(...)
repo.add(person_id, datos, procesadas)

# --- Search ---
encontrados = repo.search_by_estado(embedding, "encontrada", limite)
candidatos = [MenoresPrivacy(Candidato(**d)) for d in encontrados]

# --- Response ---
return ResultadoBusqueda(codigo=codigo, total=len(candidatos), coincidencias=candidatos)
```

#### 6.2 `registrar_encontrado` (`app/main.py:336-402`)
**Extract to `RegistrarEncontrado.execute`:**
```python
# --- Validations (4 rules) ---
if not procesadas: ...
if not refugio or not refugio.strip(): ...
if not telefono_responsable or not telefono_responsable.strip(): ...
if es_menor and not (doc_responsable and doc_responsable.strip()): ...

# --- Domain assembly ---
person_id = uuid.uuid4()
codigo = gen_codigo()
datos = { ... }  # → PersonaBase(...)
repo.add(person_id, datos, procesadas)

# --- Cross-flow search + alert ---
buscados = repo.search_by_estado(embedding, "buscada", 1)
alerta = None
if buscados:
    best = buscados[0]
    if policy.is_match(best["distancia"]):
        alerta = AlertaFamiliar(...)
        alerta = MenoresPrivacy(alerta)

# --- Response ---
return ResultadoRegistro(codigo=codigo, person_id=str(person_id), alerta=alerta)
```

#### 6.3 `buscar_admin` (`app/main.py:404-433`)
**Extract to `BuscarAdmin.execute`:**
```python
limite = max(1, min(LIMITE_MAX, limite))
results = repo.search_admin(embedding, estado, limite)
return [MenoresPrivacy(Candidato(**d)) for d in results]
```

#### 6.4 `listar` (`app/main.py:435-455`)
**Extract to `ListarPersonasAdmin.execute`:**
```python
results = repo.list_admin(limite, estado, moderacion)
return [MenoresPrivacy(PersonaAdmin(**d)) for d in results]
```

#### 6.5 `moderar` (`app/main.py:457-477`)
**Extract to `ModerarPersona.execute`:**
```python
if valor not in ("aprobada", "rechazada", "pendiente"):
    raise ...
n = repo.set_moderacion(person_id, valor)
if not n:
    raise HTTPException(404, "No existe esa persona")
return {"person_id": person_id, "moderacion": valor, "fotos_actualizadas": n}
```

#### 6.6 `eliminar` (`app/main.py:479-497`)
**Extract to `EliminarPersona.execute`:**
```python
fotos = repo.delete(person_id)
if not fotos:
    raise HTTPException(404, "No existe esa persona")
return {"person_id": person_id, "eliminada": True, "fotos": fotos}
```

---

### 7. Risks Specific to This Change

| Risk | Severity | Mitigation |
|------|----------|------------|
| **`PersonaRepository.add` signature change** | Medium | Only 2 call sites (`registrar_busqueda`, `registrar_encontrado`). After refactor, only the use cases call it. Update the SQL param mapping inside the repo. |
| **`datos` dict → `PersonaBase` round-trip** | Low | The repo currently returns `dict`s (`_row_to_candidato_dict`). The use case maps dict → Pydantic → privacy → response. This is fine; the repo can later return domain objects in a future change. |
| **Validation logic moves from endpoint to use case** | Low | The endpoint still receives form data and passes it. The use case raises domain exceptions; the endpoint maps them to HTTP status codes. |
| **Cross-flow alert mixed with registration** | Low | Document that alert construction stays in `RegistrarEncontrado` for this change. Future `cross-match` change can extract it. |
| **`MenoresPrivacy` in use case vs. endpoint** | Low | Use case applies privacy before returning. Tests verify that use case returns masked results. |
| **`admin_login` extraction ambiguity** | Low | Decide in proposal question round. Default: keep in `main.py` or extract to use case for consistency. |
| **Global accessor `get_repo()` / `get_policy()`** | Medium | Use cases receive dependencies explicitly. Endpoints can still use globals to obtain them. This decouples use cases for testing. |

---

### 8. Open Questions for the Proposal Question Round

1. **Where should `admin_login` live?**  
   - Option A: Keep in `app/main.py` (it's thin and auth-specific).  
   - Option B: Extract to `app/use_cases/admin_login.py` for consistency with other flows.  
   - Option C: Move auth logic to `app/auth.py` and make the endpoint a 3-line adapter.  
   *Implication: Consistency vs. minimal change.*

2. **Should use cases return Pydantic response models or raw dicts?**  
   - Option A: Return `ResultadoBusqueda`, `ResultadoRegistro`, `list[Candidato]`, etc. (endpoint is ultra-thin).  
   - Option B: Return dicts / domain objects; endpoint wraps in Pydantic.  
   *Implication: Option A makes the use case more coupled to the API contract but makes the endpoint trivial. Option B adds a mapping layer.*

3. **Should use cases raise domain exceptions or `HTTPException`?**  
   - Option A: Domain exceptions (`PersonaValidationError`, `PersonaNotFoundError`) mapped by endpoint.  
   - Option B: Use cases raise `HTTPException` directly.  
   *Implication: Option A keeps HTTP out of the use case layer (cleaner). Option B is less code.*

4. **Should the in-memory fake live in `tests/_fakes.py` or `app/repositories/_testing.py`?**  
   - Option A: `tests/_fakes.py` (test-only, not shipped).  
   - Option B: `app/repositories/_testing.py` (public, reusable for integration tests).  
   *Implication: Option A is cleaner. Option B enables integration tests in other packages.*

5. **Should the cross-flow alert be part of `RegistrarEncontrado` or a separate `CrossMatch` use case?**  
   - Option A: `RegistrarEncontrado` constructs the alert (current behavior, in scope).  
   - Option B: `RegistrarEncontrado` calls a `CrossMatch` service/use case (cleaner separation, but blurs scope with Change C).  
   *Implication: Option B is architecturally cleaner but may over-engineer for this change.*

---

### 9. Source File References

| File | Lines | Role |
|------|-------|------|
| `app/main.py` | 515 | Endpoints with inline orchestration (extraction target) |
| `app/domain/matching.py` | 52 | `MatchingPolicy` (pure, stays) |
| `app/domain/privacy.py` | 31 | `MenoresPrivacy` (pure, stays) |
| `app/domain/persona.py` | 49 | `PersonaBase`, `Estado`, `Foto` (domain models, stays) |
| `app/repositories/persona.py` | 304 | `PersonaRepository` (refactor `add` signature) |
| `app/auth.py` | 191 | JWT + bcrypt + admin guard (unchanged) |
| `app/schemas.py` | 95 | Pydantic request/response models (unchanged) |
| `app/faces.py` | 140 | InsightFace embedding extraction (unchanged) |
| `tests/conftest.py` | 68 | Fixtures for testing (may extend) |
| `tests/domain/test_matching.py` | 80 | 14 tests, 100% coverage (unchanged) |
| `tests/domain/test_privacy.py` | 60 | 8 tests, 100% coverage (unchanged) |

---