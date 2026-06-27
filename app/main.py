"""Servicio FastAPI de reconocimiento facial para reencuentros de personas.

Flujo:
  - POST /personas  -> sube la foto al bucket y guarda su vector facial.
  - POST /buscar    -> calcula el vector de una foto y busca rostros parecidos.
"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

# IMPORTANTE: psycopg (database) debe importarse ANTES que faces (TensorFlow).
# Si TensorFlow carga primero, las operaciones nativas de psycopg/libpq provocan
# un "free(): invalid pointer" por conflicto de librerías nativas. Este orden lo evita.
from app.config import get_settings
from app.database import close_pool, get_pool, init_db
from app import faces, storage
from app.schemas import Coincidencia, PersonaOut, ResultadoBusqueda

CONTENT_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

DESCRIPTION = """
API de **reconocimiento facial** para reunir personas desaparecidas con sus familias.

Cada foto se convierte en un **vector facial** (embedding) con DeepFace
(**SFace + retinaface**) y se compara por **distancia coseno** sobre una base
vectorial **Postgres + pgvector**. Las imágenes originales se guardan en
**DigitalOcean Spaces**.

### Flujo de uso
1. **Registrar** a la persona buscada o encontrada (`POST /personas`).
2. **Buscar** coincidencias subiendo otra foto (`POST /buscar`).

### Interpretación de la búsqueda
- `distancia` menor = más parecido (0 = idéntico).
- `es_match = true` cuando la distancia baja del **umbral** (0.55).
- Los candidatos vienen **ordenados**; la decisión final la toma una persona.
"""

tags_metadata = [
    {"name": "personas", "description": "Registrar y listar personas (buscadas / encontradas)."},
    {"name": "búsqueda", "description": "Reconocimiento facial: encontrar coincidencias por foto."},
    {"name": "sistema", "description": "Estado y salud del servicio."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_pool()  # abre el pool al arrancar
    faces.warmup()  # pre-carga modelo + detector (evita cold start en la 1ª búsqueda)
    yield
    close_pool()


app = FastAPI(
    title="Reencuentros — Reconocimiento facial",
    description=DESCRIPTION,
    version="1.0.0",
    openapi_tags=tags_metadata,
    contact={"name": "Proyecto Reencuentros"},
    license_info={"name": "Uso humanitario"},
    lifespan=lifespan,
)


@app.get("/health", tags=["sistema"], summary="Estado del servicio")
def health():
    """Devuelve `{"status": "ok"}` si el servicio está operativo."""
    return {"status": "ok"}


@app.post(
    "/personas",
    response_model=PersonaOut,
    status_code=201,
    tags=["personas"],
    summary="Registrar una persona",
    response_description="La persona registrada, con la URL de su foto en el bucket.",
)
async def registrar_persona(
    file: UploadFile = File(..., description="Foto del rostro (JPEG/PNG/WebP). Idealmente una sola cara, de frente."),
    nombre: str | None = Form(None, description="Nombre de la persona (opcional)."),
    ci: str | None = Form(None, description="Cédula o documento de identidad (opcional)."),
    rol: str | None = Form(None, description="Rol o nota libre, p. ej. quién reporta (opcional)."),
    estado: str = Form("desaparecida", description="Estado: 'buscada' (la busca un familiar) o 'encontrada' (la halló un rescatista)."),
):
    """Registra una persona: extrae su vector facial, sube la foto al bucket y
    guarda el vector + metadatos en la base vectorial.

    La primera petición tras arrancar puede tardar más (carga del modelo)."""
    data = await file.read()
    content_type = file.content_type or "image/jpeg"
    ext = CONTENT_EXT.get(content_type, "jpg")

    try:
        embedding = faces.embedding_from_bytes(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    persona_id = uuid.uuid4()
    key = f"personas/{persona_id}.{ext}"
    image_url = storage.upload_image(data, key, content_type)

    with get_pool().connection() as conn:
        row = conn.execute(
            """
            INSERT INTO personas (id, nombre, ci, rol, estado, image_url, image_key, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING created_at
            """,
            (persona_id, nombre, ci, rol, estado, image_url, key, embedding),
        ).fetchone()
        conn.commit()

    return PersonaOut(
        id=str(persona_id), nombre=nombre, ci=ci, rol=rol,
        estado=estado, image_url=image_url, created_at=row[0],
    )


@app.post(
    "/buscar",
    response_model=ResultadoBusqueda,
    tags=["búsqueda"],
    summary="Buscar coincidencias por foto",
    response_description="Candidatos ordenados por parecido, con distancia y marca de match.",
)
async def buscar(
    file: UploadFile = File(..., description="Foto del rostro a buscar (JPEG/PNG/WebP)."),
    limite: int = Form(10, description="Máximo de candidatos a devolver."),
):
    """Calcula el vector facial de la foto y devuelve los rostros registrados más
    parecidos, ordenados por distancia. `es_match` marca los de alta confianza."""
    data = await file.read()
    try:
        embedding = faces.embedding_from_bytes(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    s = get_settings()
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT id, nombre, ci, rol, estado, image_url, created_at,
                   embedding <=> %s AS distancia
            FROM personas
            ORDER BY distancia ASC
            LIMIT %s
            """,
            (embedding, limite),
        ).fetchall()

    coincidencias = [
        Coincidencia(
            id=str(r[0]), nombre=r[1], ci=r[2], rol=r[3], estado=r[4],
            image_url=r[5], created_at=r[6], distancia=float(r[7]),
            es_match=float(r[7]) < s.match_threshold,
        )
        for r in rows
    ]
    return ResultadoBusqueda(umbral=s.match_threshold, coincidencias=coincidencias)


@app.get(
    "/personas",
    response_model=list[PersonaOut],
    tags=["personas"],
    summary="Listar personas registradas",
    response_description="Personas registradas, de la más reciente a la más antigua.",
)
def listar_personas(limite: int = 50):
    """Lista las personas registradas (sin sus vectores), ordenadas por fecha."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT id, nombre, ci, rol, estado, image_url, created_at
            FROM personas
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limite,),
        ).fetchall()
    return [
        PersonaOut(
            id=str(r[0]), nombre=r[1], ci=r[2], rol=r[3],
            estado=r[4], image_url=r[5], created_at=r[6],
        )
        for r in rows
    ]
