# Tasks: `use-case` — Extract Use Cases from `app/main.py`

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 600–800 |
| 400-line budget risk | High |
| 800-line budget risk | Medium (tight margin; consider splitting) |
| Chained PRs recommended | No (single PR preferred) |
| Suggested split | single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

```
Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: High
```

**Note**: Estimated ~600–800 changed lines (net ~590 after removals). Strictly within the 800‑line review budget. A single PR is preferred. If the implementer finds the PR exceeds 800 lines during development, halt and split into Phase 1–4 + Phase 5–6 + Phase 7–8.

---

## Phase 1: Test Infrastructure (Foundation)

### Task 1.1: Verify test dependencies in `requirements.txt`

```
File: requirements.txt
```

- [ ] Confirm `pytest>=7.0`, `httpx>=0.24`, `pytest-asyncio>=0.21`, `pytest-cov>=4.0` are present.
- [ ] Add any missing packages (e.g., `pytest-asyncio` if not listed).
- [ ] Run `pip install -r requirements.txt` to ensure everything resolves.

### Task 1.2: Create test package `__init__` files

```
Files to create:
  tests/use_cases/__init__.py    (empty — test package marker)
  tests/repositories/__init__.py (empty — test package marker)
```

- [ ] Create `tests/use_cases/__init__.py` (empty file).
- [ ] Create `tests/repositories/__init__.py` (empty file).
- [ ] Verify `tests/__init__.py` already exists (it does).

### Task 1.3: Add `_map_use_case_errors` decorator in `app/main.py`

```
File: app/main.py (new helper)
```

- [ ] Add imports for the 4 domain exceptions (`PersonaValidationError`, `RostroNoDetectadoError`, `PersonaNotFoundError`, `ModificacionInvalidaError`) from `app.use_cases._exceptions`.
- [ ] Add a `_map_use_case_errors` decorator (or `_use_case_execute` / `_use_case_execute_sync` helpers) that catches the 4 domain exceptions and maps them to `HTTPException` with the correct status code:
  - `PersonaValidationError` → `422`
  - `RostroNoDetectadoError` → `422`
  - `PersonaNotFoundError` → `404`
  - `ModificacionInvalidaError` → `400`
- [ ] Wrap the sync and async variants so all 6 endpoints can reuse the mapping logic (design §4.1).

---

## Phase 2: Domain Exceptions

### Task 2.1: Create `app/use_cases/_exceptions.py`

```
File: app/use_cases/_exceptions.py (new)
```

- [ ] Define `PersonaValidationError(Exception)` with a `message` attribute.
- [ ] Define `RostroNoDetectadoError(Exception)` with a `message` attribute.
- [ ] Define `PersonaNotFoundError(Exception)` with a `message` attribute (default `"No existe esa persona"`).
- [ ] Define `ModificacionInvalidaError(Exception)` with a `message` attribute.
- [ ] Verify all 4 exceptions are importable from `app.use_cases._exceptions`.

**Design reference**: §2 — each exception has a `message` attribute used for `HTTPException.detail`.

---

## Phase 3: In-Memory Fake Repository

### Task 3.1: Create `FakePersonaRepository` at `tests/repositories/fake.py`

```
File: tests/repositories/fake.py (new)
```

- [ ] Implement `FakePersonaRepository` with these methods matching `PersonaRepository`'s public interface:
  - `add(person_id: UUID, persona: PersonaBase, procesadas) -> list[str]` — stores persona in an in‑memory list, generates fake image URLs.
  - `search_by_estado(embedding, estado: str | None, limit: int) -> list[dict]` — returns stored personas filtered by `estado` and `moderacion == "aprobada"`, with deterministic fake distances (0.10, 0.20, 0.30…).
  - `search_admin(embedding, estado: str | None, limit: int) -> list[dict]` — same as `search_by_estado` but no moderacion filter.
  - `list_admin(limit, estado=None, moderacion=None) -> list[dict]` — returns stored personas as `PersonaAdmin`-shaped dicts with optional estado/moderacion filters.
  - `set_moderacion(person_id: str, valor: str) -> int` — updates moderacion for matching personas.
  - `delete(person_id: str) -> int` — removes personas by person_id.
- [ ] Use `MatchingPolicy` (passed to constructor or default) for `_to_candidato_dict` (computes `coincidencia`, `confianza`).
- [ ] Keep the fake 100% in-memory, deterministic, and inspectable (no DB, no InsightFace).
- [ ] Add a docstring: `IMPORTANT: This is test-only infrastructure. Do NOT import from app/ code.`

**Design reference**: §6 — `_to_candidato_dict`, `_to_admin_dict` helpers; deterministic ascending distances.

---

## Phase 4: PersonaRepository Signature Change

### Task 4.1: Refactor `PersonaRepository.add` to accept `PersonaBase`

```
File: app/repositories/persona.py
```

- [ ] Change signature from `add(self, person_id: UUID, datos: dict[str, Any], procesadas)` to `add(self, person_id: UUID, persona: PersonaBase, procesadas)`.
- [ ] Inside `add`, build the `datos` dict from `persona` fields:
  - `"estado"` → `persona.estado.value`
  - `"menor"` → `persona.es_menor`
  - `"nombre"` → `persona.nombre` (and all other string fields)
  - `"tel_contacto"` → `persona.telefono_contacto`
  - `"tel_resp"` → `persona.telefono_responsable`
  - `"doc_resp"` → `persona.doc_responsable`
  - `"codigo"` → `persona.codigo` — if the use case sets it on the `PersonaBase`, or use `None` (the repo will store NULL).
- [ ] Keep the processed photo insertion loop unchanged (only the dict construction changes).
- [ ] Update the module docstring and type annotations.
- [ ] Verify no other call sites pass `dict` to `add` (only use cases will call it after refactor).

**Design reference**: §5 — `datos` dict construction inside the repository.

---

## Phase 5: Use Case Classes

### Task 5.1: Create `app/use_cases/_helpers.py`

```
File: app/use_cases/_helpers.py (new)
```

- [ ] Extract `_gen_codigo()` — generates `"REE-" + uuid.uuid4().hex[:8].upper()`.
- [ ] Extract `_embedding_consulta(procesadas)` — returns `procesadas[0][2][0][0]` if non‑empty, else `None`.
- [ ] Define type alias `ProcessedPhotos = list[tuple[bytes, str, list[tuple[np.ndarray, float]]]]`.

### Task 5.2: Create `RegistrarBusqueda` in `app/use_cases/registrar_busqueda.py`

```
File: app/use_cases/registrar_busqueda.py (new)
```

- [ ] Class `RegistrarBusqueda` with constructor: `__init__(self, repo: PersonaRepository, policy: MatchingPolicy)`.
- [ ] Method `execute(self, *, procesadas, nombre, apellido, edad, doc_tipo, doc_numero, telefono_contacto, limite) -> ResultadoBusqueda`.
- [ ] Validate: if `not procesadas` → raise `RostroNoDetectadoError`.
- [ ] Validate: if not `(doc_numero or (nombre and nombre.strip()))` → raise `PersonaValidationError`.
- [ ] Clamp `limite` to `[1, 50]`.
- [ ] Build `PersonaBase` with `estado=Estado.BUSCADA`, `es_menor=False`, `moderacion="aprobada"`, all provided form fields, and generated `person_id`/`codigo`.
- [ ] Call `self._repo.add(person_id, persona, procesadas)`.
- [ ] Call `self._repo.search_by_estado(embedding, "encontrada", limite)`.
- [ ] Apply `MenoresPrivacy` to each `Candidato(**d)` from search results.
- [ ] Return `ResultadoBusqueda(codigo, total=len(candidatos), coincidencias=candidatos)`.

**Design reference**: §3.1 — full signature, validation rules, and response assembly.

### Task 5.3: Create `RegistrarEncontrado` in `app/use_cases/registrar_encontrado.py`

```
File: app/use_cases/registrar_encontrado.py (new)
```

- [ ] Class `RegistrarEncontrado` with constructor: `__init__(self, repo: PersonaRepository, policy: MatchingPolicy)`.
- [ ] Method `execute(self, *, procesadas, es_menor, nombre, apellido, doc_tipo, doc_numero, refugio, ubicacion, telefono_responsable, doc_responsable, descripcion) -> ResultadoRegistro`.
- [ ] Validate 4 rules (design §3.2):
  1. `not procesadas` → `RostroNoDetectadoError`.
  2. `not refugio` or blank → `PersonaValidationError`.
  3. `not telefono_responsable` or blank → `PersonaValidationError`.
  4. If `es_menor and not doc_responsable` → `PersonaValidationError`.
- [ ] Build `PersonaBase` with `estado=Estado.ENCONTRADA`, `moderacion="pendiente"`, `es_menor` from input, all provided form fields.
- [ ] Call `self._repo.add(person_id, persona, procesadas)`.
- [ ] Cross‑flow search: `self._repo.search_by_estado(embedding, "buscada", 1)`.
- [ ] If match exists and `self._policy.is_match(best["distancia"])`, build `AlertaFamiliar` and apply `MenoresPrivacy`.
- [ ] Return `ResultadoRegistro(codigo, person_id=str(person_id), alerta=alerta)`.

**Design reference**: §3.2 — includes cross‑flow alert construction inside the same method.

### Task 5.4: Create `BuscarAdmin` in `app/use_cases/buscar_admin.py`

```
File: app/use_cases/buscar_admin.py (new)
```

- [ ] Class `BuscarAdmin` with constructor: `__init__(self, repo: PersonaRepository)`.
- [ ] Method `execute(self, *, embedding, estado: str | None, limite: int) -> list[Candidato]`.
- [ ] Clamp `limite` to `[1, 50]`.
- [ ] Call `self._repo.search_admin(embedding, estado, limite)`.
- [ ] Apply `MenoresPrivacy(Candidato(**d))` to each result.
- [ ] Return the list.

**Design reference**: §3.3 — admin search without moderation filter.

### Task 5.5: Create `ListarPersonasAdmin` in `app/use_cases/listar_personas_admin.py`

```
File: app/use_cases/listar_personas_admin.py (new)
```

- [ ] Class `ListarPersonasAdmin` with constructor: `__init__(self, repo: PersonaRepository)`.
- [ ] Method `execute(self, *, limite: int, estado: str | None, moderacion: str | None) -> list[PersonaAdmin]`.
- [ ] Call `self._repo.list_admin(limite, estado, moderacion)`.
- [ ] Apply `MenoresPrivacy(PersonaAdmin(**d))` to each result.
- [ ] Return the list.

**Design reference**: §3.4 — list with filters, privacy applied in use case.

### Task 5.6: Create `ModerarPersona` in `app/use_cases/moderar_persona.py`

```
File: app/use_cases/moderar_persona.py (new)
```

- [ ] Class `ModerarPersona` with constructor: `__init__(self, repo: PersonaRepository)`.
- [ ] Method `execute(self, *, person_id: str, valor: str) -> dict`.
- [ ] Validate `valor` is one of `("aprobada", "rechazada", "pendiente")` → `ModificacionInvalidaError` if not.
- [ ] Call `self._repo.set_moderacion(person_id, valor)`.
- [ ] If count is 0, raise `PersonaNotFoundError`.
- [ ] Return `{"person_id": person_id, "moderacion": valor, "fotos_actualizadas": n}`.

**Design reference**: §3.5 — validation, 404 check, response shape.

### Task 5.7: Create `EliminarPersona` in `app/use_cases/eliminar_persona.py`

```
File: app/use_cases/eliminar_persona.py (new)
```

- [ ] Class `EliminarPersona` with constructor: `__init__(self, repo: PersonaRepository)`.
- [ ] Method `execute(self, *, person_id: str) -> dict`.
- [ ] Call `self._repo.delete(person_id)`.
- [ ] If count is 0, raise `PersonaNotFoundError`.
- [ ] Return `{"person_id": person_id, "eliminada": True, "fotos": fotos}`.

**Design reference**: §3.6 — delete, 404 check, response shape.

### Task 5.8: Create `app/use_cases/__init__.py` barrel module

```
File: app/use_cases/__init__.py (new)
```

- [ ] Import and re‑export all 6 use case classes: `RegistrarBusqueda`, `RegistrarEncontrado`, `BuscarAdmin`, `ListarPersonasAdmin`, `ModerarPersona`, `EliminarPersona`.
- [ ] Populate `__all__` with the 6 class names.

**Design reference**: §3.8 — barrel module structure.

---

## Phase 6: Endpoint Refactor in `app/main.py`

### Task 6.1: Refactor `POST /buscados` to thin HTTP adapter

```
File: app/main.py ~ lines 278–334
```

- [ ] Remove inline validation, `datos` dict construction, `repo.add`, `repo.search_by_estado`, and `MenoresPrivacy` calls.
- [ ] Keep form parameter declarations, `_procesar_fotos`, use case instantiation, and `_use_case_execute` wrapper.
- [ ] Endpoint body should be ≤20 lines.
- [ ] New endpoint shape (simplified):

  ```python
  async def registrar_busqueda(files, nombre=None, apellido=None, ...):
      procesadas = await _procesar_fotos(files)
      uc = RegistrarBusqueda(get_repo(), get_policy())
      return await _use_case_execute(uc.execute, procesadas=procesadas, ...)
  ```

### Task 6.2: Refactor `POST /encontrados` to thin HTTP adapter

```
File: app/main.py ~ lines 336–402
```

- [ ] Remove inline validation, `datos` dict construction, `repo.add`, cross‑flow search, alert construction, and `MenoresPrivacy`.
- [ ] Keep form parameter declarations, `_procesar_fotos`, use case instantiation, and `_use_case_execute`.
- [ ] Endpoint body ≤20 lines.

### Task 6.3: Refactor `POST /buscar` to thin HTTP adapter

```
File: app/main.py ~ lines 404–433
```

- [ ] Remove `limite` clamping, `repo.search_admin`, and `MenoresPrivacy`.
- [ ] Keep `file.read()`, `faces.embedding_from_bytes`, use case instantiation, and `_use_case_execute`.
- [ ] Endpoint body ≤20 lines.

### Task 6.4: Refactor `GET /admin/personas` to thin HTTP adapter

```
File: app/main.py ~ lines 435–455
```

- [ ] Remove `repo.list_admin` and `MenoresPrivacy`.
- [ ] Keep query param parsing, use case instantiation, `_use_case_execute_sync`.
- [ ] Endpoint body ≤10 lines.

### Task 6.5: Refactor `PATCH /admin/personas/{id}/moderacion` to thin HTTP adapter

```
File: app/main.py ~ lines 457–477
```

- [ ] Remove inline validation of `valor`, `repo.set_moderacion`, 404 check.
- [ ] Keep path param, query param, use case instantiation, `_use_case_execute_sync`.
- [ ] Endpoint body ≤10 lines.

### Task 6.6: Refactor `DELETE /admin/personas/{id}` to thin HTTP adapter

```
File: app/main.py ~ lines 479–497
```

- [ ] Remove `repo.delete` and 404 check.
- [ ] Keep path param, use case instantiation, `_use_case_execute_sync`.
- [ ] Endpoint body ≤10 lines.

### Task 6.7: Keep `POST /admin/login` and `GET /health` unmodified

```
Files: app/main.py
```

- [ ] `GET /health` stays as is (2-line docstring + return).
- [ ] `POST /admin/login` stays as is (~22 lines, no `PersonaRepository` dependency).
- [ ] Verify imports: remove unused imports (if any) from `app/main.py` after refactor.

---

## Phase 7: Unit Tests for Use Cases

### Task 7.1: Tests for `RegistrarBusqueda`

```
File: tests/use_cases/test_registrar_busqueda.py (new)
```

At minimum (design §7.1):

- [ ] `test_happy_path_with_nombre` — name provided, returns `ResultadoBusqueda` with matches.
- [ ] `test_happy_path_with_doc_numero` — doc_numero provided (no name), returns matches.
- [ ] `test_raises_rostro_no_detectado` — empty `procesadas` → `RostroNoDetectadoError`.
- [ ] `test_raises_persona_validation_no_name_no_doc` — neither nombre nor doc_numero → `PersonaValidationError`.
- [ ] `test_limite_clamped_to_1` — limite=0 → clamped to 1.
- [ ] `test_limite_clamped_to_50` — limite=100 → clamped to 50.
- [ ] `test_applies_menores_privacy_on_candidates` — minors have `nombre=None`, `apellido=None`.
- [ ] `test_adult_names_preserved` — adults have real names intact.
- [ ] `test_repo_add_called_with_persona_base_not_dict` — assert repo received `PersonaBase` instance.
- [ ] `test_repo_add_called_with_estado_buscada` — `PersonaBase.estado == Estado.BUSCADA`.
- [ ] `test_repo_add_called_with_moderacion_aprobada` — `PersonaBase.moderacion == "aprobada"`.
- [ ] `test_empty_search_returns_zero_total` — no matches → total=0, empty coincidencias.
- [ ] `test_codigo_is_generated` — result has `codigo` starting with `"REE-"`.

### Task 7.2: Tests for `RegistrarEncontrado`

```
File: tests/use_cases/test_registrar_encontrado.py (new)
```

At minimum (design §7.2):

- [ ] `test_happy_path_no_match` — valid registration, no cross‑match, `alerta=None`.
- [ ] `test_happy_path_with_match` — cross‑match exists, alerta is populated.
- [ ] `test_alerta_menor_masks_nombre` — match is minor, `alerta.familiar_nombre` is `None`.
- [ ] `test_alerta_non_minor_preserves_nombre` — match is adult, `familiar_nombre` preserved.
- [ ] `test_minor_name_stored_not_nulled` — minor's nombre stored in persona, only masked in response.
- [ ] `test_raises_rostro_no_detectado` — empty procesadas → `RostroNoDetectadoError`.
- [ ] `test_raises_persona_validation_no_refugio` — missing refugio → `PersonaValidationError`.
- [ ] `test_raises_persona_validation_no_telefono_responsable` — missing telefono_responsable → error.
- [ ] `test_raises_persona_validation_menor_sin_doc_responsable` — `es_menor=True`, no doc_responsable → error.
- [ ] `test_repo_add_called_with_estado_encontrada` — `PersonaBase.estado == Estado.ENCONTRADA`.
- [ ] `test_repo_add_called_with_moderacion_pendiente` — `PersonaBase.moderacion == "pendiente"`.
- [ ] `test_repo_add_called_with_es_menor_true` — `PersonaBase.es_menor` matches input.

### Task 7.3: Tests for `BuscarAdmin`

```
File: tests/use_cases/test_buscar_admin.py (new)
```

At minimum (design §7.3):

- [ ] `test_happy_path_returns_candidates` — valid embedding returns list of `Candidato`.
- [ ] `test_limite_clamped` — limite=0 → 1, limite=100 → 50.
- [ ] `test_filters_by_estado` — estado="buscada" returns only buscada.
- [ ] `test_applies_menores_privacy` — minor candidates masked.
- [ ] `test_no_moderacion_filter` — admin search returns all moderacion statuses.

### Task 7.4: Tests for `ListarPersonasAdmin`

```
File: tests/use_cases/test_listar_personas_admin.py (new)
```

At minimum (design §7.4):

- [ ] `test_happy_path_returns_personas` — returns list of `PersonaAdmin`.
- [ ] `test_filters_by_estado` — estado filter works.
- [ ] `test_filters_by_moderacion` — moderacion filter works.
- [ ] `test_applies_menores_privacy` — minor personas masked.
- [ ] `test_respects_limite` — returns at most `limit` results.
- [ ] `test_empty_list_when_no_data` — returns `[]` when fake repo empty.

### Task 7.5: Tests for `ModerarPersona`

```
File: tests/use_cases/test_moderar_persona.py (new)
```

At minimum (design §7.5):

- [ ] `test_happy_path_aprobada` — valid valor → dict with `fotos_actualizadas`.
- [ ] `test_happy_path_rechazada` — same for "rechazada".
- [ ] `test_happy_path_pendiente` — same for "pendiente".
- [ ] `test_raises_modificacion_invalida` — valor="invalido" → `ModificacionInvalidaError`.
- [ ] `test_raises_persona_not_found` — non‑existent person_id → `PersonaNotFoundError`.
- [ ] `test_exception_has_message` — error message matches expected string.

### Task 7.6: Tests for `EliminarPersona`

```
File: tests/use_cases/test_eliminar_persona.py (new)
```

At minimum (design §7.6):

- [ ] `test_happy_path_deletes_persona` — valid person_id → dict with fotos count.
- [ ] `test_raises_persona_not_found` — non‑existent person_id → `PersonaNotFoundError`.
- [ ] `test_persona_removed_from_fake` — after delete, persona no longer in repo.
- [ ] `test_exception_has_message` — error message matches expected string.

### Task 7.7: Tests for domain exceptions (scattered or separate)

```
Files: any test file (scattered in the use case tests above, or a dedicated file)
```

- [ ] Each of the 4 domain exceptions is raised in at least one test in the use case test suite.
- [ ] Each exception carries an appropriate error message (assert on `str(exc_info.value)`).

---

## Phase 8: Verification

### Task 8.1: Run `pytest`

- [ ] Run `python -m pytest tests/ -v` from the repo root.
- [ ] All existing 22 domain tests pass.
- [ ] All new use case tests pass.
- [ ] Fix any failures before proceeding.

### Task 8.2: Run coverage check

- [ ] Run `python -m pytest tests/ --cov=app/use_cases --cov-report=term-missing`.
- [ ] Verify ≥80% line coverage on `app/use_cases/`.
- [ ] Verify `app/domain/` still reports 100% coverage (62/62 statements).

### Task 8.3: Manual smoke test of each endpoint

- [ ] `GET /health` — returns `{"status": "ok"}`.
- [ ] `POST /admin/login` — returns JWT with valid credentials.
- [ ] `POST /buscados` — with a test image, returns `ResultadoBusqueda`.
- [ ] `POST /encontrados` — with a test image, returns `ResultadoRegistro`.
- [ ] `POST /buscar` — with Bearer token, returns `list[Candidato]`.
- [ ] `GET /admin/personas` — with Bearer token, returns `list[PersonaAdmin]`.
- [ ] `PATCH /admin/personas/{id}/moderacion` — valid and invalid valor.
- [ ] `DELETE /admin/personas/{id}` — valid and non‑existent id.

### Task 8.4: Verify API contract preserved

- [ ] Compare response shapes pre/post refactor for all 6 refactored endpoints.
- [ ] Confirm `AlertaFamiliar` shape is identical for cross‑flow matches.
- [ ] Confirm error status codes are unchanged (422, 404, 400, 401, 403).
- [ ] Confirm no new fields or removed fields in any response model.

---

## Verification Matrix

| Spec Requirement | Task(s) | How verified |
|---|---|---|
| One use case class per flow | 5.2–5.8 | Code review: each file exports one class with `execute()` |
| Endpoints are ≤20 lines each | 6.1–6.7 | Code review + line count |
| Use cases return Pydantic response models | 5.2–5.6 | Type annotations + test assertions on return type |
| Domain exceptions raised by use cases | 2.1, 7.7 | Each exception is raised in ≥1 test |
| Endpoints map domain exceptions to HTTP codes | 1.3, 6.1–6.6 | Decorator maps all 4 exceptions |
| `PersonaRepository.add` accepts `PersonaBase` | 4.1 | Signature change + test asserts `isinstance(persona, PersonaBase)` |
| Cross-flow alert stays in `RegistrarEncontrado` | 5.3 | Alert construction internal to `execute()` |
| `MenoresPrivacy` applied inside each use case | 5.2, 5.4, 5.5 | Tests verify minor masking |
| In‑memory fake at `tests/repositories/fake.py` | 3.1 | File exists, used in all use case tests |
| Use case tests ≥80% coverage | 7.1–7.7, 8.2 | `pytest --cov=app/use_cases` reports ≥80% |
| API contract preserved | 8.4 | Response shape comparison pre/post |
| Existing domain tests pass (22 tests) | 8.1 | `pytest tests/domain/` passes |
| `admin_login` stays in `app/main.py` | 6.7 | Not extracted to use case |
| `_procesar_fotos` stays in HTTP boundary | 6.1, 6.2 | Remains in `app/main.py` |
