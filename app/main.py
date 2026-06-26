"""Servicio FastAPI de reconocimiento facial de personas desaparecidas.

Flujo:
  - POST /personas  -> sube la foto a Spaces y guarda su embedding en Postgres.
  - POST /buscar    -> calcula el embedding de una foto y busca rostros parecidos.
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_pool()  # abre el pool al arrancar
    yield
    close_pool()


app = FastAPI(
    title="Reconocimiento facial — personas desaparecidas",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/personas", response_model=PersonaOut, status_code=201)
async def registrar_persona(
    file: UploadFile = File(...),
    nombre: str | None = Form(None),
    ci: str | None = Form(None),
    rol: str | None = Form(None),
    estado: str = Form("desaparecida"),
):
    """Registra una persona: sube la imagen a Spaces y guarda el embedding."""
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
        id=str(persona_id),
        nombre=nombre,
        ci=ci,
        rol=rol,
        estado=estado,
        image_url=image_url,
        created_at=row[0],
    )


@app.post("/buscar", response_model=ResultadoBusqueda)
async def buscar(file: UploadFile = File(...), limite: int = Form(10)):
    """Busca los rostros más parecidos a la imagen enviada."""
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
            id=str(r[0]),
            nombre=r[1],
            ci=r[2],
            rol=r[3],
            estado=r[4],
            image_url=r[5],
            created_at=r[6],
            distancia=float(r[7]),
            es_match=float(r[7]) < s.match_threshold,
        )
        for r in rows
    ]
    return ResultadoBusqueda(umbral=s.match_threshold, coincidencias=coincidencias)


@app.get("/personas", response_model=list[PersonaOut])
def listar_personas(limite: int = 50):
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
            id=str(r[0]),
            nombre=r[1],
            ci=r[2],
            rol=r[3],
            estado=r[4],
            image_url=r[5],
            created_at=r[6],
        )
        for r in rows
    ]
