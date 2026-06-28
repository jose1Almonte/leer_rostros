# CLAUDE.md

This file provides guidance to AI agents and contributors working on this repository.

## What is this

**Reencuentros** — a facial-recognition web app for reuniting missing persons with their families. Stack: **Python 3.11**, **FastAPI**, **InsightFace buffalo_l** (ArcFace w600k_r50, 512-dim embeddings), **PostgreSQL 16 + pgvector** (HNSW index, cosine distance), **DigitalOcean Spaces** (S3-compatible, local fallback). Admin auth via **JWT + bcrypt**.

## How to run

```bash
# With Docker (recommended)
docker-compose up -d

# Without Docker (requires Postgres with pgvector)
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Config in `.env` (see `app/config.py`):

- `match_threshold=0.55` (InsightFace-calibrated cosine distance threshold)
- `jwt_secret`, `jwt_expires_minutes`, `jwt_algorithm` (auth)

## Architecture

The app is organized as **bounded contexts** under `app/`:

```
app/
  main.py                  # FastAPI endpoints + lifespan + acceso a policy/repos
  domain/                  # lógica de dominio pura (sin SQL ni HTTP)
    matching.py            #   MatchingPolicy
    privacy.py             #   MenoresPrivacy
    persona.py             #   Estado enum, PersonaBase
  shared/                  # ⭐ utilidades compartidas por bounded contexts
    _exceptions.py         #   PersonaValidationError, PersonaNotFoundError, …
    _helpers.py            #   LIMITE_MAX, _gen_codigo, _embedding_consulta
  personas/                # ⭐ bounded context: personas + persona_embeddings
    repositories/
      persona.py           #   PersonaRepository: SQL de personas + embeddings
    use_cases/
      registrar_busqueda.py
      registrar_encontrado.py
      agregar_historial.py     #   trazabilidad: nuevo avistamiento de una persona
      ver_trazabilidad.py      #   trazabilidad: histórico (admin, con teléfono)
      ver_trazabilidad_publica.py  # trazabilidad: histórico público (sin teléfono)
      ver_ficha_persona.py     #   búsqueda inversa por cédula + histórico (admin)
      buscar_admin.py
      listar_personas_admin.py
      moderar_persona.py
      eliminar_persona.py
  reportes/                # ⭐ bounded context: tabla reportes
    repositories/
      reporte.py           #   ReporteRepository: SQL de reportes
    use_cases/
      registrar_falla.py
      registrar_publicacion.py
      listar_reportes_admin.py
      cambiar_estado_reporte.py
  auth.py                  # JWT + bcrypt, admins table, get_current_admin
  cli.py                   # CLI for admin management
  schemas.py               # Pydantic models
  config.py                # Settings via pydantic-settings
  database.py              # init_db() with pgvector + admins + persona_historial
  faces.py                 # InsightFace buffalo_l
  storage.py               # Image upload/download (Spaces or local fallback)
```

### Main flows

1. **FAMILIAR** (`POST /buscados`): Uploads photo of missing person, searches among found persons. Returns ranked candidates. **Text shortcut:** if the familiar provides `doc_numero` + `nombre` (and `apellido` if given) that match an `encontrada` **exactly** (normalized: trim + lowercase), it returns that 100% match and **skips the facial search** entirely. Any mismatch falls back to the embedding search.
2. **RESCATISTA** (`POST /encontrados`): Registers a found person. If a familiar was already searching, generates `AlertaFamiliar` (by **face**).
   - **Reverse search by cédula:** if a familiar (`buscada`) was already searching for the same `doc_numero`, the response carries `coincidencias_familiares` (list of `AlertaFamiliar`, 100% by exact document) so the rescatista can reach them. Complements the face-based `alerta`.
   - **Dedup by cédula + trazabilidad:** if a `doc_numero` already exists among `encontrada` people, the response carries `alerta_duplicado` and **no duplicate is created**. Resend with `confirmar_duplicado=true` to append the new sighting to that person's history instead. Every new found person also gets a first `persona_historial` event ("registro inicial").
3. **TRAZABILIDAD** — flow of 3 steps:
   - **Write** (`POST /encontrados/{person_id}/historial`, public): a rescatista logs a new sighting (location/refugio/timestamp) for an existing person; it also updates the person's current location (COALESCE — never wipes a field with NULL).
   - **Read public** (`GET /encontrados/{person_id}/historial`, public): **anyone** can see the trace (chronological sightings) of a **visible** (aprobada) person. **Omits the phone** (`TrazaPersonaPublica` / `EventoHistorialPublico`). 404 if not visible.
   - **Read admin** (`GET /admin/personas/{person_id}/historial`, admin): full trace **with phone**, works regardless of moderation. The combined **dossier** — who was searching for this person (reverse by cédula) **plus** the full history — is at `GET /admin/personas/{person_id}/coincidencias` (admin).
4. **PUBLIC REPORTES** (`POST /reportes/falla`, `POST /reportes/publicacion`): Anyone can report a bug or an inadequate publication.
5. **ADMIN** (`POST /buscar`, `GET /admin/personas`, `PATCH .../moderacion`, `DELETE`, `GET /admin/personas/{id}/historial`, `GET /admin/reportes`, `PATCH /admin/reportes/{id}/estado`): Requires Bearer token.

### Privacy protocol

Minor names are **stored** in the DB but **masked** in all regular API responses (public AND admin) via `MenoresPrivacy`. This protects identity without losing data.

### Multi-embeddings per photo

Each photo generates 1 base embedding + up to 2 augmentations (rotations ±15°), stored in `persona_embeddings`. Searches use `ROW_NUMBER() OVER (PARTITION BY person_id ORDER BY embedding <=> query ASC)` for best match per person.

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ \
  --cov=app/domain \
  --cov=app/personas/use_cases \
  --cov=app/reportes/use_cases \
  --cov=app/shared \
  --cov-report=term-missing
```

Tests are organized by bounded context:

- `tests/domain/` — pure-domain unit tests (`matching.py`, `privacy.py`).
- `tests/personas/use_cases/` + `tests/personas/repositories/fake.py` — `FakePersonaRepository` enables testing without PostgreSQL or InsightFace.
- `tests/reportes/use_cases/` + `tests/reportes/repositories/fake.py` — same pattern for the reportes flow.

Current state: **100 tests, ~0.6s runtime, 100% coverage on use cases and shared**.

## CI

- `.github/workflows/tests.yml` — runs on every `pull_request` to `master`. Marked as a **required status check** in branch protection so failing tests block the merge.
- `.github/workflows/deploy.yml` — runs on `push` to `master` (post-merge). It has `needs: test`, so even if branch protection is bypassed the deploy is gated by the test job.

## Key notes

- `app/main.py` has **no inline SQL** for `personas`/`persona_embeddings` — all via `PersonaRepository`. Same for `reportes` — all via `ReporteRepository`.
- Domain exceptions live in `app/shared/_exceptions.py` and are mapped to HTTP status codes by the `_use_case_execute` helper in `app/main.py`:
  - `PersonaValidationError` → 422
  - `RostroNoDetectadoError` → 422
  - `PersonaNotFoundError` → 404 (used for both `persona` and `reporte` lookups)
  - `ModificacionInvalidaError` → 400
- `match_threshold=0.55` loaded from `Settings` at startup. `MatchingPolicy.match_percentage` delegates to `faces.distance_to_confidence` (sigmoid, k=12.0, midpoint=0.40).
- V0 prototype files removed: `load_image.py`, `search_image.py`, `main.py` (root), `haarcascade_frontalface_default.xml`.
- Nested repo `leer_rostros/` is in `.gitignore` — do not work inside it.
- When working on a bounded context, keep all of its code under `app/<context>/` and its tests under `tests/<context>/`. Cross-cutting concerns go to `app/shared/` and `tests/conftest.py`.
