# CLAUDE.md

This file provides guidance to AI agents and contributors working on this repository.

## Qué es

**Reencuentros** — aplicación web de reconocimiento facial para reunir personas desaparecidas con sus familias. Stack: **Python 3.11**, **FastAPI**, **InsightFace buffalo_l** (ArcFace w600k_r50, 512-dim embeddings), **PostgreSQL 16 + pgvector** (HNSW index, cosine distance), **DigitalOcean Spaces** (S3-compatible, con fallback a disco local). Autenticación admin vía **JWT + bcrypt**.

## Ejecutar

```bash
# Con Docker (recomendado)
docker-compose up -d

# Sin Docker (requiere Postgres con pgvector)
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Configuración en `.env` (ver `app/config.py`):

- `match_threshold=0.55` (umbral de coincidencia, calibrado para InsightFace)
- `jwt_secret`, `jwt_expires_minutes`, `jwt_algorithm` (auth)

## Arquitectura

```
app/
  main.py            # FastAPI endpoints: /buscados, /encontrados, /buscar, /admin/*
  domain/
    matching.py      # MatchingPolicy: threshold, confidence bands, percentage (sigmoid)
    privacy.py       # MenoresPrivacy: enmascara nombres de menores en respuestas API
    persona.py       # Estado enum, Foto dataclass, PersonaBase model
  repositories/
    persona.py       # PersonaRepository: todo el SQL para personas + persona_embeddings
  auth.py            # JWT + bcrypt, admins table, get_current_admin dependency
  cli.py             # CLI para gestión de admins (crear/listar/eliminar)
  schemas.py         # Pydantic models: Candidato, PersonaAdmin, AlertaFamiliar, etc.
  config.py          # Settings via pydantic-settings
  database.py        # init_db() con pgvector + tabla admins
  faces.py           # InsightFace buffalo_l: detección + embedding + augmentations
  storage.py         # Upload/download de imágenes (Spaces o local)
```

### Flujos principales

1. **FAMILIAR** (`POST /buscados`): Sube foto de persona buscada, busca entre encontradas. Devuelve coincidencias rankeadas.
2. **RESCATISTA** (`POST /encontrados`): Registra persona encontrada. Si un familiar ya la buscaba, genera `AlertaFamiliar`.
3. **ADMIN** (`POST /buscar`, `GET /admin/personas`, `PATCH .../moderacion`, `DELETE`): Requiere Bearer token. Búsqueda, listado, moderación, eliminación.

### Privacy protocol

Los nombres de menores se **almacenan** en la DB pero se **enmascaran** en todas las respuestas API regulares (públicas y admin) vía `MenoresPrivacy`. Esto protege la identidad sin perder datos.

### Multi-embeddings por foto

Cada foto genera 1 embedding base + hasta 2 augmentations (rotaciones ±15°), almacenados en `persona_embeddings`. Las búsquedas usan `ROW_NUMBER() OVER (PARTITION BY person_id ORDER BY embedding <=> query ASC)` para obtener el mejor match por persona.

## Testing

```bash
# Correr todos los tests
python -m pytest tests/ -v

# Con coverage
python -m pytest tests/ --cov=app/domain --cov=app/repositories --cov-report=term-missing
```

Tests unitarios en `tests/domain/` y `tests/repositories/`. No requieren DB ni modelo cargado.

## Notas

- `app/main.py` **no contiene SQL inline** para tablas `personas`/`persona_embeddings` — todo va vía `PersonaRepository`.
- El umbral `match_threshold=0.55` se carga desde `Settings` al inicio. `MatchingPolicy.match_percentage` delega a `faces.distance_to_confidence` (sigmoid, k=12.0, midpoint=0.40).
- Archivos v0 eliminados: `load_image.py`, `search_image.py`, `main.py` (root), `haarcascade_frontalface_default.xml`.
- Repo anidado `leer_rostros/` en `.gitignore` — no trabajar dentro.
