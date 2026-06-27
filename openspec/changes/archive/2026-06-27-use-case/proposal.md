# Proposal: `use-case` — Extract Use Cases from `app/main.py`

## Intent

This change introduces a dedicated use-case layer between FastAPI endpoints and the domain/repository layers. Today, `app/main.py` (515 lines) contains all endpoint orchestration: form parsing, validation, `datos` dict construction, repository calls, privacy application, cross-flow alert construction, and response shaping. This single file mixes HTTP concerns with business flow, making the system hard to test, hard to extend, and risky to change. By extracting one use-case class per flow, endpoints become thin HTTP adapters (5–12 lines each), the `PersonaBase` domain object actually flows through the system instead of being bypassed by raw dicts, and the use-case layer becomes independently testable with in-memory fakes.

## Decisions

The following decisions were made during the proposal question round and are binding for this change:

1. **Q1 — `admin_login` location**: Keep `admin_login` in `app/main.py`. The endpoint is already thin (~22 lines) and does not touch `PersonaRepository`; extracting it adds a file for little gain.
2. **Q2 — Use case return type**: Use cases return Pydantic response models (`ResultadoBusqueda`, `ResultadoRegistro`, `list[Candidato]`, etc.). The endpoint is ultra-thin (`return use_case.execute(...)`). The use case is coupled to the API wire format by design.
3. **Q3 — Exception style**: Use cases raise domain exceptions (`PersonaValidationError`, `PersonaNotFoundError`, `RostroNoDetectadoError`, etc.). The endpoint catches and maps them to HTTP status codes. This keeps HTTP out of the business layer.
4. **Q4 — Fake repository location**: The in-memory fake for `PersonaRepository` lives at `tests/repositories/fake.py`. It is test-only infrastructure, organized by layer.
5. **Q5 — Cross-flow alert**: The cross-flow `AlertaFamiliar` construction stays inside `RegistrarEncontrado`. One class per flow keeps the change simple; extracting it is a separate Change C.

## Why now

Four pain points make this the right next step after `core-domain`:

1. **`app/main.py` has too many responsibilities**. Each endpoint function does form parsing, validation, dict building, repository orchestration, privacy application, and response construction. The file is 515 lines and growing; adding a new endpoint means copying the same 40-line pattern.

2. **`PersonaBase` exists but is unused in the main flow**. The domain model from `core-domain` (`PersonaBase`) is defined in `app/domain/persona.py`, but endpoints still build raw `datos: dict[str, Any]` with Spanish SQL parameter names (`"menor"`, `"tel_contacto"`, `"tel_resp"`). The domain object is bypassed entirely.

3. **No unit tests for the orchestration layer**. The 22 existing tests cover `MatchingPolicy` and `MenoresPrivacy` (pure domain logic), but there are zero tests for the flows that wire them together: "register a missing person, search for matches, apply privacy, return ranked candidates." Testing this today requires booting the full FastAPI app.

4. **Adding a new endpoint requires copying boilerplate**. The pattern of `uuid4() + gen_codigo() + datos dict + repo.add() + search + MenoresPrivacy + response` is repeated twice (buscados, encontrados) with slight variations. A use-case layer would eliminate this duplication and make the intent of each flow explicit.

## Scope

### In scope

- **New `app/use_cases/` module** with one class per flow:
  - `RegistrarBusqueda` — FAMILIAR flow (`POST /buscados`)
  - `RegistrarEncontrado` — RESCATISTA flow (`POST /encontrados`)
  - `BuscarAdmin` — ADMIN photo search (`POST /buscar`)
  - `ListarPersonasAdmin` — ADMIN list (`GET /admin/personas`)
  - `ModerarPersona` — ADMIN moderation (`PATCH .../moderacion`)
  - `EliminarPersona` — ADMIN delete (`DELETE .../{person_id}`)
- **Refactor `app/main.py` endpoint functions** to be thin HTTP adapters (parse form/files, call use case, map exceptions, return response).
- **`PersonaRepository.add` signature change**: accept `PersonaBase` (domain object) instead of `dict[str, Any]`. The repository maps fields to SQL parameters internally.
- **In-memory fake `PersonaRepository`** for use-case unit tests (test-only, lives at `tests/repositories/fake.py`).
- **Unit tests for each use case** covering happy paths and validation edge cases.
- **(Optional) Integration tests** with FastAPI `TestClient` + Bearer token fixture for auth-gate verification.

### Out of scope (deferred)

- **FaceEmbedder seam** (Candidate 4): `faces.embeddings_from_bytes` remains a concrete function call at the HTTP boundary. Abstracting it behind an interface is a separate change.
- **Cross-match module** (Candidate 7): The cross-flow alert construction stays inside `RegistrarEncontrado` for this change. Extracting it as a standalone `CrossMatch` service belongs to a future change.
- **Repository integration tests** with real PostgreSQL+pgvector: still deferred.
- **Admin login extraction**: `admin_login` stays in `app/main.py`.

## Product outcomes

After this change lands:

- **Each business flow has a single, named home**. "How does a rescuer register a found person?" → read `RegistrarEncontrado.execute`. The answer is no longer scattered across 66 lines of `app/main.py`.
- **Each endpoint becomes a thin HTTP adapter**: it parses form data, calls `use_case.execute(...)`, and returns the Pydantic response.
- **The use case raises domain exceptions; the endpoint catches and maps them to HTTP status codes** (422, 404, etc.).
- **`PersonaBase` is the canonical internal representation**. Form fields become a domain object before reaching the repository. The Spanish `datos` dict disappears from endpoints.
- **The use-case layer is testable without InsightFace or PostgreSQL**. Unit tests inject the in-memory fake and verify validation rules, search orchestration, privacy application, and cross-flow alerts in milliseconds.
- **The in-memory fake for `PersonaRepository` lives at `tests/repositories/fake.py`** for use-case unit tests.
- **The cross-flow `AlertaFamiliar` construction stays inside `RegistrarEncontrado`**; extracting it is a separate Change C.
- **`admin_login` stays in `app/main.py`** (not extracted into a use case).
- **Adding a new flow requires writing one class, not copying a 40-line pattern**. The structure is self-documenting for future contributors.

## Affected areas

| File | Nature of change |
|------|-----------------|
| `app/main.py` | Heavy refactor: remove validation, dict construction, orchestration, and privacy application from endpoint functions. Endpoints become thin adapters (~5–12 lines each). Net reduction of ~200–250 lines. |
| **New** `app/use_cases/__init__.py` | Barrel module exporting all use-case classes. |
| **New** `app/use_cases/registrar_busqueda.py` | `RegistrarBusqueda` class: validation, `PersonaBase` construction, `repo.add`, search, privacy, response assembly. |
| **New** `app/use_cases/registrar_encontrado.py` | `RegistrarEncontrado` class: 4 validation rules, `PersonaBase` construction, `repo.add`, cross-flow search + alert construction, privacy, response assembly. |
| **New** `app/use_cases/buscar_admin.py` | `BuscarAdmin` class: clamp limit, `repo.search_admin`, privacy application. |
| **New** `app/use_cases/listar_personas_admin.py` | `ListarPersonasAdmin` class: `repo.list_admin`, privacy application. |
| **New** `app/use_cases/moderar_persona.py` | `ModerarPersona` class: validate moderation value, `repo.set_moderacion`, 404 check. |
| **New** `app/use_cases/eliminar_persona.py` | `EliminarPersona` class: `repo.delete`, 404 check. |
| **New** `app/use_cases/_exceptions.py` | Domain exceptions used by use cases: `PersonaValidationError`, `PersonaNotFoundError`, `RostroNoDetectadoError`, etc. |
| `app/repositories/persona.py` | Refactor `add` signature: `dict[str, Any]` → `PersonaBase`. Internal mapping from `PersonaBase` fields to SQL parameter names. |
| **New** `tests/repositories/fake.py` | `FakePersonaRepository` implementing the repository interface in memory. |
| **New** `tests/use_cases/` | Unit tests for each use case using the in-memory fake (`tests/repositories/fake.py`). |
| `tests/conftest.py` | May extend fixtures (e.g., `fake_repo`, `use_case` factories). |
| `app/domain/persona.py` | Possibly extend `PersonaBase` if new fields are needed for the refactored flows. |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **`PersonaRepository.add` signature change breaks callers** | Low | Medium | Only 2 call sites today (`registrar_busqueda`, `registrar_encontrado`). After refactor, only the use cases call it. Update SQL param mapping inside the repo once. |
| **The endpoint's try/except mapping layer adds boilerplate** | Medium | Low | It keeps the use case reusable and HTTP-agnostic. The mapping is explicit and one-to-one with domain exceptions. |
| **Pydantic coupling means changing a response field requires touching the use case** | Low | Low | Document the response field ownership in the use case module. The tradeoff is accepted for ultra-thin endpoints. |
| **`MenoresPrivacy` applied in use case instead of endpoint — tests must verify masking** | Low | Medium | Each use-case test that returns persona data asserts that minors are masked. The endpoint tests verify only HTTP wiring. |
| **Cross-flow alert mixed with registration use case** | Low | Low | Alert construction stays in `RegistrarEncontrado` for this change. A future `cross-match` change can extract it without touching the use-case boundary. |
| **`tests/repositories/fake.py` must be kept in sync with the real `PersonaRepository` interface** | Medium | Low | A CI test could verify the fake implements the same interface. The fake only needs to support query patterns used by use cases. |
| **`app/main.py` refactor is large and touches all endpoints at once** | Medium | Medium | The change is mechanical extraction — no behavioral change. Use integration tests to verify endpoint contracts remain intact. Review budget is 800 lines; estimated 600–800 lines changed. |

## Rollback

If the change breaks production:

1. **Revert `app/main.py`** to the pre-refactor state (restore inline orchestration).
2. **Remove `app/use_cases/`** directory.
3. **Revert `app/repositories/persona.py`** `add` signature to accept `dict[str, Any]`.
4. **Remove new tests** under `tests/use_cases/` and `tests/repositories/fake.py`.
5. **Database**: No schema changes. No data migration. Safe to revert code only.

## Success criteria

1. **Each endpoint function in `app/main.py` is at most 20 lines of HTTP plumbing** (form parsing + use case call + try/except mapping).
2. **Each use case raises domain exceptions, not `HTTPException`**. The endpoint maps `PersonaValidationError` → 422, `PersonaNotFoundError` → 404, etc.
3. **`PersonaRepository.add(person: PersonaBase, processed_photos, ...)` accepts a domain object, not a dict**. No Spanish `datos` dict remains in endpoints.
4. **All use cases have unit tests using the in-memory fake** (`tests/repositories/fake.py`). Tests cover happy paths, validation failures, and edge cases.
5. **Test coverage on `app/use_cases/` ≥80%**.
6. **Privacy protocol is preserved**: All use cases that return persona data apply `MenoresPrivacy` before returning. Tests verify masking for minors and passthrough for adults.
7. **No behavioral regression in public API shapes**: `POST /buscados`, `POST /encontrados`, `POST /buscar`, `GET /admin/personas`, `PATCH /admin/personas/{id}/moderacion`, and `DELETE /admin/personas/{id}` return the same response shapes and status codes.
8. **All existing tests pass**: `pytest tests/` passes with 22+ domain tests and new use-case tests.
9. **Cross-flow alert still works**: `RegistrarEncontrado` constructs `AlertaFamiliar` when `policy.is_match()` is true, and applies `MenoresPrivacy` to it.

## Proposal question round — answered

1. **Q1 — Where should `admin_login` live?** → **A**: Keep it in `app/main.py`.
2. **Q2 — Should use cases return Pydantic response models or raw/domain objects?** → **A**: Return Pydantic response models; endpoint is ultra-thin.
3. **Q3 — Should use cases raise domain exceptions or `HTTPException`?** → **A**: Raise domain exceptions; endpoint maps to HTTP status codes.
4. **Q4 — Where should the in-memory fake repository live?** → **C**: `tests/repositories/fake.py`.
5. **Q5 — Should the cross-flow alert construction stay inside `RegistrarEncontrado` or be extracted now?** → **A**: Keep it inside `RegistrarEncontrado`.
