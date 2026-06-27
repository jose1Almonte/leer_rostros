# Use-Case Layer Specification

## Purpose

This specification defines the use-case layer that sits between FastAPI endpoints and the domain/repository layers in the reencuentros service. After this change, each business flow has a single, named use-case class in `app/use_cases/` that encapsulates validation, domain-object construction, repository orchestration, privacy application, and response assembly. Endpoints in `app/main.py` become thin HTTP adapters (≤20 lines) that parse requests, call the use case's `execute` method, catch domain exceptions, and map them to HTTP status codes. The `PersonaBase` domain object flows through the system instead of being bypassed by raw dicts, and the use-case layer becomes independently testable with in-memory fakes.

## Requirements

### Use Case Module

#### Requirement: One use case class per flow

The system MUST provide a use case module at `app/use_cases/` with one class per business flow:

- `RegistrarBusqueda` — FAMILIAR flow (`POST /buscados`)
- `RegistrarEncontrado` — RESCATISTA flow (`POST /encontrados`)
- `BuscarAdmin` — ADMIN photo search (`POST /buscar`)
- `ListarPersonasAdmin` — ADMIN list (`GET /admin/personas`)
- `ModerarPersona` — ADMIN moderation (`PATCH /admin/personas/{id}/moderacion`)
- `EliminarPersona` — ADMIN delete (`DELETE /admin/personas/{id}`)

`admin_login` (`POST /admin/login`) MUST remain in `app/main.py` and MUST NOT be extracted into a use case.

`GET /health` MUST remain as a direct endpoint and MUST NOT have a use case.

#### Scenario: Use case module structure

- GIVEN the project is built
- WHEN the `app/use_cases/` directory is listed
- THEN there is one Python file per use case class plus an `__init__.py` barrel module

#### Scenario: Each use case has a single execute method

- GIVEN a use case class (e.g., `RegistrarBusqueda`)
- WHEN it is instantiated with its dependencies (`PersonaRepository`, `MatchingPolicy` as applicable)
- THEN it exposes a public `execute(...)` method that performs the full flow and returns a Pydantic response model

### Endpoint Thinness

#### Requirement: Endpoints are HTTP adapters

Each endpoint function in `app/main.py` that delegates to a use case MUST be at most 20 lines and MUST contain only:

1. Request parsing (form data, query params, path params, file uploads)
2. Face-processing calls (`_procesar_fotos`, `_embedding_consulta`) at the HTTP boundary
3. Use case instantiation and `execute(...)` invocation inside a `try/except` block
4. Domain exception catching and mapping to `HTTPException` with the appropriate status code
5. Return of the Pydantic response model from the use case

The endpoint MUST NOT contain business logic, validation rules, `PersonaBase` construction, repository calls, `MenoresPrivacy` application, `MatchingPolicy` calls, `AlertaFamiliar` construction, or response field assembly.

#### Scenario: Endpoint for POST /buscados

- GIVEN a `POST /buscados` request with valid form data and uploaded files
- WHEN the request is processed
- THEN the endpoint parses the form, calls `_procesar_fotos`, instantiates `RegistrarBusqueda`, calls `execute(...)`, and returns the `ResultadoBusqueda`
- AND the endpoint body is at most 20 lines of code

#### Scenario: Endpoint for POST /encontrados

- GIVEN a `POST /encontrados` request with valid form data and uploaded files
- WHEN the request is processed
- THEN the endpoint parses the form, calls `_procesar_fotos`, instantiates `RegistrarEncontrado`, calls `execute(...)`, and returns the `ResultadoRegistro`
- AND the endpoint body is at most 20 lines of code

### Use Case Return Type

#### Requirement: Use cases return Pydantic response models

Each use case's `execute` method MUST return the same Pydantic response model that the corresponding endpoint returns:

| Use case | Return type |
|---|---|
| `RegistrarBusqueda.execute` | `ResultadoBusqueda` |
| `RegistrarEncontrado.execute` | `ResultadoRegistro` |
| `BuscarAdmin.execute` | `list[Candidato]` |
| `ListarPersonasAdmin.execute` | `list[PersonaAdmin]` |
| `ModerarPersona.execute` | `dict` with `person_id`, `moderacion`, `fotos_actualizadas` |
| `EliminarPersona.execute` | `dict` with `person_id`, `eliminada`, `fotos` |

#### Scenario: RegistrarBusqueda.execute returns ResultadoBusqueda

- GIVEN valid processed photos and form data
- WHEN `RegistrarBusqueda.execute(...)` is called
- THEN it returns a `ResultadoBusqueda` Pydantic model with `codigo`, `total`, and `coincidencias` fields populated

### Domain Exceptions

#### Requirement: Use case module defines domain exceptions

The system MUST define a domain exception module at `app/use_cases/_exceptions.py` (or equivalent) with the following exceptions:

- `PersonaValidationError` — raised when form data is invalid (missing required fields, no face detected, business rule violations)
- `RostroNoDetectadoError` — raised when no face is detected in an uploaded photo (may be a subclass of `PersonaValidationError` or a distinct exception)
- `PersonaNotFoundError` — raised when a `person_id` does not exist in the database
- `ModificacionInvalidaError` — raised when an invalid moderation value is provided

Use cases MUST raise these domain exceptions. Use cases MUST NOT raise `HTTPException` or any HTTP-framework-specific exception.

#### Requirement: Endpoints map domain exceptions to HTTP status codes

Each endpoint that calls a use case MUST catch domain exceptions and map them to HTTP status codes:

- `PersonaValidationError` → `HTTPException(status_code=422)`
- `RostroNoDetectadoError` → `HTTPException(status_code=422)`
- `PersonaNotFoundError` → `HTTPException(status_code=404)`
- `ModificacionInvalidaError` → `HTTPException(status_code=400)`

#### Scenario: Validation error maps to 422

- GIVEN a request to `POST /buscados` with no `nombre` and no `doc_numero`
- WHEN the request is processed
- THEN `RegistrarBusqueda.execute(...)` raises `PersonaValidationError`
- AND the endpoint catches it and raises `HTTPException(status_code=422, detail=<message>)`

#### Scenario: Rostro no detectado maps to 422

- GIVEN a request with a photo that has no detectable face
- WHEN `RegistrarBusqueda.execute(...)` is called
- THEN it raises `RostroNoDetectadoError`
- AND the endpoint catches it and raises `HTTPException(status_code=422, detail=<message>)`

#### Scenario: Person not found maps to 404

- GIVEN a request to `DELETE /admin/personas/{id}` with a non-existent `person_id`
- WHEN the request is processed
- THEN `EliminarPersona.execute(...)` raises `PersonaNotFoundError`
- AND the endpoint catches it and raises `HTTPException(status_code=404, detail=<message>)`

#### Scenario: Invalid moderation maps to 400

- GIVEN a request to `PATCH /admin/personas/{id}/moderacion` with `valor="invalido"`
- WHEN the request is processed
- THEN `ModerarPersona.execute(...)` raises `ModificacionInvalidaError`
- AND the endpoint catches it and raises `HTTPException(status_code=400, detail=<message>)`

### PersonaBase Flow

#### Requirement: PersonaRepository.add accepts a PersonaBase

`PersonaRepository.add` MUST accept a `PersonaBase` (Pydantic model from `app/domain/persona.py`) as its primary data argument instead of a `dict[str, Any]`.

The repository MUST internally map `PersonaBase` fields to SQL parameter names (e.g., `persona.es_menor` → `%(menor)s`, `persona.telefono_contacto` → `%(tel_contacto)s`).

#### Scenario: Repository accepts a domain object

- GIVEN a use case that has constructed a `PersonaBase` from form data
- WHEN `repo.add(person_id, persona, procesadas)` is called
- THEN the row is inserted into `personas` with values mapped from `persona` fields
- AND N rows are inserted into `persona_embeddings` (one per processed photo × N embeddings)

#### Scenario: Use case builds PersonaBase from form fields (FAMILIAR)

- GIVEN form data with `nombre`, `apellido`, `edad`, `doc_tipo`, `doc_numero`, `telefono_contacto`
- WHEN `RegistrarBusqueda.execute(...)` is called
- THEN a `PersonaBase` is constructed with:
  - `estado = Estado.BUSCADA`
  - `es_menor = False`
  - `moderacion = "aprobada"`
  - All provided form fields mapped to corresponding `PersonaBase` fields
- AND the `PersonaBase` is passed to `repo.add`

#### Scenario: Use case builds PersonaBase from form fields (RESCATISTA)

- GIVEN form data with `es_menor`, `nombre`, `apellido`, `refugio`, `telefono_responsable`, `doc_responsable`, `descripcion`, `ubicacion`
- WHEN `RegistrarEncontrado.execute(...)` is called
- THEN a `PersonaBase` is constructed with:
  - `estado = Estado.ENCONTRADA`
  - `es_menor` set from form input
  - `moderacion = "pendiente"` (found persons start pending moderation)
  - All provided form fields mapped to corresponding `PersonaBase` fields
- AND the `PersonaBase` is passed to `repo.add`

### Cross-flow Alert

#### Requirement: AlertaFamiliar construction stays inside RegistrarEncontrado

`RegistrarEncontrado.execute(...)` MUST construct the `AlertaFamiliar` (when a cross-flow match exists) internally. The alert construction logic MUST NOT be extracted to a separate use case or service in this change.

When the found person's best embedding match against `buscada` persons has a distance below `MatchingPolicy.threshold`, the result MUST include an `AlertaFamiliar` with the matched person's details.

#### Scenario: Alert is created when a familiar match exists

- GIVEN a found person whose best embedding match against `buscada` persons has distance < threshold
- WHEN `RegistrarEncontrado.execute(...)` is called
- THEN the returned `ResultadoRegistro` includes an `AlertaFamiliar` populated with the matched person's details
- AND `MenoresPrivacy` is applied to the alert (masking `familiar_nombre` if the matched person is a minor)

#### Scenario: No alert when no match exists

- GIVEN a found person whose best embedding match has distance >= threshold
- WHEN `RegistrarEncontrado.execute(...)` is called
- THEN the returned `ResultadoRegistro` has `alerta = None`

### Privacy Application

#### Requirement: MenoresPrivacy is applied inside each use case

Each use case that returns persona data MUST apply `MenoresPrivacy` to all returned objects before returning. The use case is responsible for privacy application; the endpoint MUST NOT call `MenoresPrivacy`.

Use cases that MUST apply `MenoresPrivacy`:

- `RegistrarBusqueda` — applies to each `Candidato` in `coincidencias`
- `RegistrarEncontrado` — applies to the `AlertaFamiliar` in the result (if present)
- `BuscarAdmin` — applies to each `Candidato` in the result list
- `ListarPersonasAdmin` — applies to each `PersonaAdmin` in the result list

#### Scenario: RegistrarBusqueda applies MenoresPrivacy

- GIVEN a search returns 10 candidates, 3 of which are minors (`es_menor=True`)
- WHEN `RegistrarBusqueda.execute(...)` returns
- THEN the 3 minor candidates have `nombre=None` and `apellido=None`
- AND the 7 adult candidates have their real names intact

#### Scenario: RegistrarEncontrado applies MenoresPrivacy to alert

- GIVEN a cross-flow match where the matched `buscada` person is a minor
- WHEN `RegistrarEncontrado.execute(...)` returns
- THEN the `AlertaFamiliar` in the result has `familiar_nombre=None`

### In-Memory Fake Repository

#### Requirement: Fake repository for testing

An in-memory fake implementation of `PersonaRepository` MUST exist at `tests/repositories/fake.py`. The fake MUST implement the same public interface as the real `PersonaRepository`:

- `add(person_id, persona: PersonaBase, procesadas) -> list[str]`
- `search_by_estado(embedding, estado, limit) -> list[dict]`
- `search_admin(embedding, estado, limit) -> list[dict]`
- `list_admin(limit, estado, moderacion) -> list[dict]`
- `set_moderacion(person_id, valor) -> int`
- `delete(person_id) -> int`

The fake MUST be test-only and MUST NOT be imported by application code.

#### Scenario: Fake repository supports use case tests

- GIVEN a use case test that instantiates a `FakePersonaRepository`
- WHEN `fake.add(...)` is called followed by `fake.search_by_estado(...)`
- THEN the search returns the previously added person data in the expected dict shape
- AND `MatchingPolicy` is used to compute match decisions

### Test Coverage

#### Requirement: Use case test coverage ≥80%

`pytest` MUST pass with ≥80% line coverage on `app/use_cases/`.

#### Scenario: Coverage report passes

- GIVEN all use case tests pass
- WHEN `pytest --cov=app/use_cases --cov-report=term-missing` is run
- THEN the reported line coverage on `app/use_cases/` is ≥80%

#### Requirement: Domain exceptions are unit-tested

Each domain exception (`PersonaValidationError`, `RostroNoDetectadoError`, `PersonaNotFoundError`, `ModificacionInvalidaError`) MUST be triggered by at least one use case unit test that verifies:

- The exception type is raised
- The exception carries an appropriate error message

#### Scenario: PersonaValidationError triggered in RegistrarBusqueda

- GIVEN a use case test for `RegistrarBusqueda` with no `nombre` and no `doc_numero`
- WHEN `RegistrarBusqueda.execute(...)` is called
- THEN it raises `PersonaValidationError`

#### Scenario: PersonaNotFoundError triggered in EliminarPersona

- GIVEN a use case test for `EliminarPersona` with a `person_id` not in the fake repository
- WHEN `EliminarPersona.execute(...)` is called
- THEN it raises `PersonaNotFoundError`

### Backward Compatibility

#### Requirement: API contract preserved

The HTTP API contract (endpoint routes, request shapes, response shapes, status codes) MUST be preserved after this change. API clients MUST NOT need to change their integration code.

#### Scenario: Same response shape for POST /buscados

- GIVEN a valid `POST /buscados` request made before and after this change
- WHEN both requests are processed
- THEN both responses have the same `ResultadoBusqueda` shape (`codigo`, `total`, `coincidencias`)

#### Scenario: Same response shape for POST /encontrados

- GIVEN a valid `POST /encontrados` request made before and after this change
- WHEN both requests are processed
- THEN both responses have the same `ResultadoRegistro` shape (`codigo`, `person_id`, `alerta`)

#### Scenario: Same response shape for admin endpoints

- GIVEN valid admin requests to `GET /admin/personas`, `PATCH /admin/personas/{id}/moderacion`, and `DELETE /admin/personas/{id}` made before and after this change
- WHEN the requests are processed
- THEN the response bodies and status codes are identical

### Existing Tests

#### Requirement: Existing domain tests continue to pass

All existing tests in `tests/domain/` (22 tests covering `MatchingPolicy` and `MenoresPrivacy`) MUST continue to pass after this change.

#### Scenario: Domain tests pass

- GIVEN this change is applied
- WHEN `pytest tests/domain/` is run
- THEN all 22 tests pass with 100% coverage on `app/domain/`
