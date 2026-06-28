# AGENTS.md

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
  testimonios/             # ⭐ bounded context: tabla testimonios
    repositories/
      testimonio.py        #   TestimonioRepository: SQL de testimonios
    use_cases/
      registrar_testimonio.py
      listar_testimonios_publico.py
      listar_testimonios_admin.py
      moderar_testimonio.py
      eliminar_testimonio.py
  auth.py                  # JWT + bcrypt, admins table, get_current_admin
  cli.py                   # CLI for admin management
  schemas.py               # Pydantic models
  config.py                # Settings via pydantic-settings
  database.py              # init_db() with pgvector + admins table
  faces.py                 # InsightFace buffalo_l
  storage.py               # Image upload/download (Spaces or local fallback)
```

### Main flows

1. **FAMILIAR** (`POST /buscados`): Uploads photo of missing person, searches among found persons. Returns ranked candidates.
2. **RESCATISTA** (`POST /encontrados`): Registers a found person. If a familiar was already searching, generates `AlertaFamiliar`.
3. **PUBLIC REPORTES** (`POST /reportes/falla`, `POST /reportes/publicacion`): Anyone can report a bug or an inadequate publication.
4. **TESTIMONIOS** (`POST /testimonios`, `GET /personas/{id}/testimonios`): Anyone can upload a photo/video testimonial of a successful reunion, optionally linked to a `person_id`. Testimonios start as `pendiente` until admin approval.
5. **ADMIN** (`POST /buscar`, `GET /admin/personas`, `PATCH .../moderacion`, `DELETE`, `GET /admin/reportes`, `PATCH /admin/reportes/{id}/estado`, `GET /admin/testimonios`, `PATCH /admin/testimonios/{id}/estado`, `DELETE /admin/testimonios/{id}`): Requires Bearer token.

### Privacy protocol

Minor names are **stored** in the DB but **masked** in all regular API responses (public AND admin) via `MenoresPrivacy`. This protects identity without losing data.

### Multi-embeddings per photo

Each photo generates 1 base embedding + up to 2 augmentations (rotations ±15°), stored in `persona_embeddings`. Searches use `ROW_NUMBER() OVER (PARTITION BY person_id ORDER BY embedding <=> query ASC)` for best match per person.

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=app/domain --cov=app/repositories --cov-report=term-missing
```

Unit tests in `tests/domain/` and `tests/repositories/`. No DB or model loading required.

## Key notes

- `app/main.py` has **no inline SQL** for `personas`/`persona_embeddings` — all via `PersonaRepository`.
- `match_threshold=0.55` loaded from `Settings` at startup. `MatchingPolicy.match_percentage` delegates to `faces.distance_to_confidence` (sigmoid, k=12.0, midpoint=0.40).
- V0 prototype files removed: `load_image.py`, `search_image.py`, `main.py` (root), `haarcascade_frontalface_default.xml`.
- Nested repo `leer_rostros/` is in `.gitignore` — do not work inside it.
