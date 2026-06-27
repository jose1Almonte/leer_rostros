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
  main.py            # FastAPI endpoints: /buscados, /encontrados, /buscar, /admin/*
  domain/
    matching.py      # MatchingPolicy: threshold, confidence bands, percentage (sigmoid)
    privacy.py       # MenoresPrivacy: masks minor names in API responses
    persona.py       # Estado enum, Foto dataclass, PersonaBase model
  repositories/
    persona.py       # PersonaRepository: all SQL for personas + persona_embeddings
  auth.py            # JWT + bcrypt, admins table, get_current_admin dependency
  cli.py             # CLI for admin management (create/list/delete)
  schemas.py         # Pydantic models: Candidato, PersonaAdmin, AlertaFamiliar, etc.
  config.py          # Settings via pydantic-settings
  database.py        # init_db() with pgvector + admins table
  faces.py           # InsightFace buffalo_l: detection + embedding + augmentations
  storage.py         # Image upload/download (Spaces or local fallback)
```

### Main flows

1. **FAMILIAR** (`POST /buscados`): Uploads photo of missing person, searches among found persons. Returns ranked candidates.
2. **RESCATISTA** (`POST /encontrados`): Registers a found person. If a familiar was already searching, generates `AlertaFamiliar`.
3. **ADMIN** (`POST /buscar`, `GET /admin/personas`, `PATCH .../moderacion`, `DELETE`): Requires Bearer token. Search, list, moderate, delete.

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
