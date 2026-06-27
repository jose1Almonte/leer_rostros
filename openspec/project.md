# Reencuentros — Project Context

## Purpose

Facial-recognition service for reuniting missing persons with their families after
a humanitarian crisis (Venezuela earthquake). A family member uploads a photo of
the person they're looking for; a rescuer uploads a photo of someone they found;
the system performs facial matching and alerts when a match is found.

## Stack

| Component | Technology | Role |
|-----------|-----------|------|
| **API** | FastAPI + uvicorn (pm2-managed, nginx reverse proxy) | REST endpoints, Swagger at `/api/docs` |
| **Face engine** | InsightFace buffalo_l (ArcFace w600k_r50, 512-dim) + RetinaFace detector | 512-dim embedding extraction with ±15° rotation augmentations |
| **Vector DB** | PostgreSQL 16 + pgvector (HNSW index, cosine distance) | Vector storage and similarity search |
| **Image storage** | DigitalOcean Spaces (S3-compatible, boto3) with local fallback | Original image persistence |
| **Auth** | JWT (HS256) + bcrypt, `admins` table | Admin endpoint protection |
| **Configuration** | pydantic-settings (.env) | Environment-based config |
| **Schemas** | pydantic v2 | Request/response validation |

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
  cli.py             # CLI for admin management (create/list/delete/activate)
  schemas.py         # Pydantic models: Candidato, PersonaAdmin, AlertaFamiliar, etc.
  config.py          # Settings via pydantic-settings
  database.py        # init_db() with pgvector + admins table
  faces.py           # InsightFace buffalo_l: detection + embedding + augmentations
  storage.py         # Image upload/download (Spaces or local fallback)
```

## Endpoints

| Method | Route | Tags | Auth | Description |
|--------|-------|------|------|-------------|
| `GET` | `/health` | sistema | — | Service health check |
| `POST` | `/admin/login` | admin | — | Login, returns JWT |
| `POST` | `/buscados` | familiar | — | Register missing person search, return matches |
| `POST` | `/encontrados` | rescatista | — | Register found person, alert if family searched |
| `POST` | `/buscar` | admin | Bearer | Compare photo against entire database (no moderation filter) |
| `GET` | `/admin/personas` | admin | Bearer | List all records with optional estado/moderacion filters |
| `PATCH` | `/admin/personas/{id}/moderacion` | admin | Bearer | Update moderation status |
| `DELETE` | `/admin/personas/{id}` | admin | Bearer | Delete persona (cascades embeddings, cleans storage) |

## Domain Model

- **personas** table (one row per photo, multiple photos share `person_id`):
  - `id` (UUID PK), `person_id` (UUID, groups photos), `estado` ('buscada'|'encontrada')
  - `es_menor` (bool — triggers privacy protocol)
  - `nombre`, `apellido`, `edad`, `doc_tipo`, `doc_numero`
  - `telefono_contacto`, `refugio`, `telefono_responsable`, `doc_responsable`
  - `descripcion`, `ubicacion`, `codigo` (e.g., "REE-XXXXXXXX")
  - `image_url`, `image_key`, `moderacion` ('aprobada'|'rechazada'|'pendiente'), `created_at`
- **persona_embeddings** table (N rows per photo: 1 base + up to 2 rotations ±15°):
  - `id` (UUID PK), `foto_id` (UUID FK → `personas.id` ON DELETE CASCADE)
  - `embedding` (vector(512), L2-normalized), `calidad_rostro` (float), `created_at`
- **admins** table:
  - `id` (UUID PK), `username` (TEXT UNIQUE), `password_hash` (bcrypt), `is_active` (bool)
  - `created_at`, `last_login_at`

## Design Decisions

1. **Model choice**: InsightFace buffalo_l (ArcFace w600k_r50, 512-dim) + RetinaFace
   — selected after evaluating 5 models × 3 detectors on real labeled photos.
2. **Match threshold**: 0.55 (cosine distance). Calibrated for InsightFace: same-person
   ≤0.25 (typical), different-people ≥0.55.
3. **Confidence formula**: Sigmoid (k=12.0, midpoint=0.40) replaces old Facenet512
   `1.2` divisor. At distance 0.10 → ~97%, 0.40 → ~50%, 0.55 → ~16%.
4. **HNSW index** (not ivfflat): ivfflat skips rows with small datasets; HNSW works
   correctly at any scale.
5. **Import order**: `app.database` (psycopg) must be imported before `app.faces`
   (InsightFace/TensorFlow) to avoid `free(): invalid pointer` crash.
6. **Privacy protocol**: Minor names are **stored** in DB but **masked** in ALL regular
   API responses (public AND admin) via `MenoresPrivacy` at the response boundary.
   Applied to: `/buscados`, `/encontrados` (AlertaFamiliar), `/buscar`, `/admin/personas`.
7. **Multi-embeddings per photo**: Each photo generates 1 base embedding + up to 2
   augmentations (rotations ±15°), stored in `persona_embeddings`. Searches use
   `ROW_NUMBER() OVER (PARTITION BY person_id ORDER BY embedding <=> query ASC)`.
8. **Moderation filter**: Public searches always filter by `moderacion = 'aprobada'`.
   Admin can list by any status and update via PATCH.
9. **Admin auth**: JWT (HS256) + bcrypt, table-backed. CLI for admin management
   (`python -m app.cli`). Bootstrap from env vars if table is empty.
10. **SQL ownership**: All SQL for `personas`/`persona_embeddings` lives in
    `app/repositories/persona.py`. No inline SQL for these tables in `app/main.py`.
11. **Domain layer**: Pure business logic in `app/domain/` (no SQL, no HTTP).
    `MatchingPolicy`, `MenoresPrivacy`, `PersonaBase`.

## Infrastructure

- **Droplet**: DigitalOcean (137.184.107.94), Ubuntu 24.04
- **Domain**: symtechven.com (nginx reverse proxy, SSL via Certbot)
- **Docker**: docker-compose (api + pgvector/pgvector:pg16)
- **Volumes**: 20 GB volume for code, venv, InsightFace weights, and Postgres data
- **Process manager**: pm2 (service name: `rostros-api`)

## Testing

- **Runner**: pytest
- **Discipline**: Tests alongside code (NOT strict TDD)
- **Coverage**: 100% on `app/domain/` (62/62 statements, 22 tests)
  - `tests/domain/test_matching.py` — 14 tests
  - `tests/domain/test_privacy.py` — 8 tests
- **Repository layer**: 0% coverage (requires live PostgreSQL + pgvector)
- **Fixtures**: `client` (TestClient with auth override), `policy`, `admin`, `admin_token`, `admin_headers`

```bash
# Run all tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=app/domain --cov=app/repositories --cov-report=term-missing
```

## Active Change: use-case

See `openspec/changes/use-case/` for change-specific artifacts.

Scope:

- Extract use case module per flow from `app/main.py`
- PersonaRepository.add accepts `PersonaBase` (not dict)
- Endpoints become thin HTTP adapters
- Unit tests for use cases with in-memory fakes
