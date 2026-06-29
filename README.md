# Reencuentros

**Reencuentros** es una aplicación web de reconocimiento facial para reunir personas desaparecidas con sus familias. Permite a familiares buscar personas mediante foto, a rescatistas registrar personas encontradas, y genera alertas cuando hay una coincidencia.

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | Python 3.11 + FastAPI |
| Reconocimiento facial | InsightFace buffalo_l (ArcFace w600k_r50, embeddings 512-dim) |
| Base de datos | PostgreSQL 16 + pgvector (índice HNSW, distancia coseno) |
| Almacenamiento | DigitalOcean Spaces (S3, con fallback local) |
| Frontend | HTML estático servido por nginx |
| Proxy | nginx (también sirve frontend) |
| Auth admin | JWT + bcrypt |

## Requisitos

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/) (incluido con Docker Desktop)

## Configuración

1.  Cloná el repositorio:

    ```bash
    git clone https://github.com/jose1Almonte/leer_rostros.git
    cd leer_rostros
    ```

2.  Creá un archivo `.env` en la raíz (podés copiar `.env.example`):

    ```env
    # --- Almacenamiento (opcional: si se omite, usa disco local) ---
    SPACES_KEY=tu_key
    SPACES_SECRET=tu_secret
    SPACES_REGION=sfo3
    SPACES_BUCKET=tu_bucket

    # --- Base de datos (default: postgres local) ---
    DATABASE_URL=postgresql://rostros:rostros@localhost:5432/rostros

    # --- Reconocimiento facial ---
    MATCH_THRESHOLD=0.55
    MIN_FACE_QUALITY=0.50

    # --- Admin (solo para seed inicial) ---
    ADMIN_USER=admin
    ADMIN_PASSWORD=

    # --- JWT (OBLIGATORIO en producción) ---
    # Generá uno con: python -c "import secrets; print(secrets.token_urlsafe(64))"
    JWT_SECRET=poner_un_secreto_seguro_aqui
    ```

3.  Levantá todo:

    ```bash
    docker compose up -d --build
    ```

4.  Abrí [http://localhost](http://localhost).

## Uso

### Flujo principal

1. **FAMILIAR** → `POST /buscados` — Sube foto(s) de la persona desaparecida. El sistema extrae el rostro con InsightFace, genera embeddings (base + rotaciones ±15°), y busca entre las personas encontradas. Devuelve candidatos ordenados por similitud facial.
2. **RESCATISTA** → `POST /encontrados` — Registra una persona encontrada con foto(s) y datos. Si un familiar ya estaba buscando a esa persona, genera una `AlertaFamiliar` automáticamente.
3. **RESCATISTA** → `POST /encontrados/verificar` — Flujo inverso: sube foto de una persona hallada y ve si alguien la está buscando, sin registrar nada.
4. **Cualquier persona** puede reportar fallas, publicaciones inadecuadas, y subir testimonios de reencuentros exitosos.

### Admin

Los endpoints de admin requieren autenticación Bearer JWT.

1. `POST /admin/login` — Obtener token
2. Usar header `Authorization: Bearer <token>` en el resto

### API endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Estado del servicio |
| `POST` | `/admin/login` | Login de admin → JWT |
| `POST` | `/buscados` | Familiar: registrar búsqueda |
| `GET` | `/buscados/{codigo}/coincidencias` | Familiar: paginar coincidencias |
| `POST` | `/encontrados` | Rescatista: registrar encontrado |
| `POST` | `/encontrados/verificar` | Rescatista: verificar sin registrar |
| `POST` | `/encontrados/{id}/historial` | Rescatista: agregar avistamiento |
| `POST` | `/encontrados/importar` | Admin: importar encontrado por URL |
| `POST` | `/buscar` | Admin: buscar contra toda la base |
| `POST` | `/buscar/paginated` | Admin: buscar paginado |
| `GET` | `/admin/personas` | Admin: listar personas |
| `PATCH` | `/admin/personas/{id}/moderacion` | Admin: moderar publicación |
| `DELETE` | `/admin/personas/{id}` | Admin: eliminar |
| `POST` | `/reportes/falla` | Reportar falla técnica |
| `POST` | `/reportes/publicacion` | Reportar publicación inadecuada |
| `GET` | `/admin/reportes` | Admin: listar reportes |
| `PATCH` | `/admin/reportes/{id}/estado` | Admin: cambiar estado de reporte |
| `POST` | `/testimonios` | Subir testimonio de reencuentro |
| `GET` | `/personas/{id}/testimonios` | Testimonios públicos de una persona |
| `GET` | `/admin/testimonios` | Admin: listar testimonios |
| `PATCH` | `/admin/testimonios/{id}/estado` | Admin: moderar testimonio |
| `DELETE` | `/admin/testimonios/{id}` | Admin: eliminar testimonio |

La documentación interactiva (Swagger) está en `/api/docs`.

### CLI de administración

```bash
# Ver todos los admins
docker compose exec api python -m app.cli list-admins

# Crear un admin
docker compose exec api python -m app.cli create-admin --user jefe

# Cambiar contraseña
docker compose exec api python -m app.cli change-password jefe

# Desactivar / activar un admin
docker compose exec api python -m app.cli deactivate-admin jefe
docker compose exec api python -m app.cli activate-admin jefe
```

## Arquitectura

```
app/
  main.py                   # FastAPI endpoints + lifespan
  auth.py                   # JWT + bcrypt (tabla admins)
  config.py                 # Settings vía pydantic-settings
  database.py               # init_db() + pool (pgvector)
  faces.py                  # InsightFace buffalo_l
  storage.py                # Spaces o fallback local
  schemas.py                # Pydantic models
  cli.py                    # CLI de admins
  domain/                   # Lógica de dominio pura
    matching.py             #   MatchingPolicy
    privacy.py              #   MenoresPrivacy (enmascara menores)
    persona.py              #   Estado enum, PersonaBase
  shared/                   # Utilidades compartidas
    _exceptions.py          #   Excepciones de dominio
    _helpers.py             #   Funciones auxiliares
  personas/                 # Bounded context: personas + embeddings
    repositories/persona.py #   SQL de personas y embeddings
    use_cases/              #   Casos de uso (registrar, buscar, listar, etc.)
  reportes/                 # Bounded context: reportes
    repositories/reporte.py #   SQL de reportes
    use_cases/              #   Casos de uso (registrar, listar, moderar)
  testimonios/              # Bounded context: testimonios
    repositories/testimonio.py
    use_cases/
```

### Reconocimiento facial

- **Modelo**: InsightFace buffalo_l (RetinaFace para detección + ArcFace w600k_r50 para reconocimiento).
- **Embeddings**: 512 dimensiones, almacenados en columna `vector(512)` de pgvector con índice HNSW.
- **Augmentación**: cada foto genera 1 embedding base + hasta 2 rotaciones (±15°), almacenados como filas separadas en `persona_embeddings`. Las búsquedas toman el mejor match por persona via `ROW_NUMBER()`.
- **Umbral**: `match_threshold=0.55` (distancia coseno). La confianza se calcula con una sigmoide (`k=12.0`, midpoint `0.40`).

### Privacidad de menores

Los nombres de menores se almacenan en BD pero se enmascaran en todas las respuestas de la API cuando la coincidencia facial es baja (<20%). En vistas de admin se muestran siempre completos.

## Pruebas

```bash
python -m pytest tests/ -v
```

## Desarrollo sin Docker

```bash
# Requiere Postgres con pgvector corriendo
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
