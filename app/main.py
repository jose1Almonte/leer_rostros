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
from app.schemas import Coincidencia, FotosAgregadasOut, PersonaOut, ResultadoBusqueda

CONTENT_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

DESCRIPTION = """
API de **reconocimiento facial** para reunir personas desaparecidas con sus familias.

Cada foto se convierte en un **vector facial** (embedding, 512-dim) con
**InsightFace buffalo_l** (ArcFace w600k_r50 + RetinaFace) y se compara por
**distancia coseno** sobre una base vectorial **Postgres + pgvector (HNSW)**.
Las imágenes originales se guardan en **DigitalOcean Spaces**.

### Flujo de uso
1. **Registrar** a la persona buscada o encontrada (`POST /personas`).
   Puedes subir varias fotos (frente, 3/4, perfil) para mayor robustez ante ángulos.
2. **Buscar** coincidencias subiendo otra foto (`POST /buscar`).
3. *(Opcional)* **Agregar fotos** a una persona ya registrada (`POST /personas/{id}/fotos`).

### Interpretación de la búsqueda
- `confianza` (0–100 %): >70 % = alta confianza; 30–70 % = revisar con humano; <30 % = baja confianza.
- `es_match = true` cuando la distancia baja del **umbral** configurable.
- Los candidatos vienen **ordenados** por el mejor embedding de cada persona; la decisión final la toma una persona.
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
    files: list[UploadFile] = File(..., description="Una o más fotos del rostro (JPEG/PNG/WebP). Subir varias (frente, 3/4, perfil) mejora la precisión ante distintos ángulos."),
    nombre: str | None = Form(None, description="Nombre de la persona (opcional)."),
    ci: str | None = Form(None, description="Cédula o documento de identidad (opcional)."),
    rol: str | None = Form(None, description="Rol o nota libre, p. ej. quién reporta (opcional)."),
    estado: str = Form("desaparecida", description="Estado: 'buscada' (la busca un familiar) o 'encontrada' (la halló un rescatista)."),
):
    """Registra una persona: extrae vectores faciales de todas las fotos enviadas
    (más augmentaciones por rotación), sube la primera foto al bucket y guarda
    los vectores + metadatos en la base vectorial.

    Enviar fotos desde distintos ángulos aumenta significativamente la tasa de
    reconocimiento posterior. La primera petición puede tardar más (descarga del modelo)."""
    if not files:
        raise HTTPException(status_code=400, detail="Se requiere al menos una foto.")
    if len(files) > 3:
        raise HTTPException(status_code=400, detail="Máximo 3 fotos por registro.")

    # Leer todos los archivos antes de procesar.
    file_data: list[tuple[bytes, str]] = []
    for f in files:
        file_data.append((await f.read(), f.content_type or "image/jpeg"))

    # Extraer embeddings de todas las fotos + augmentaciones.
    all_embeddings: list[tuple] = []
    for i, (data, _) in enumerate(file_data):
        try:
            embs = faces.embeddings_from_bytes(data)
            all_embeddings.extend(embs)
        except ValueError as e:
            if i == 0:
                # La primera foto es obligatoria; si falla, abortamos.
                raise HTTPException(status_code=400, detail=str(e))
            # Fotos adicionales que fallen se omiten silenciosamente.

    if not all_embeddings:
        raise HTTPException(status_code=400, detail="No se detectó ningún rostro en ninguna de las fotos enviadas.")

    main_data, main_content_type = file_data[0]
    ext = CONTENT_EXT.get(main_content_type, "jpg")
    persona_id = uuid.uuid4()

    # Subir TODAS las fotos al bucket (no solo la primera).
    image_urls: list[str] = []
    image_keys: list[str] = []
    for i, (data, ct) in enumerate(file_data):
        fext = CONTENT_EXT.get(ct, "jpg")
        key = f"personas/{persona_id}/{i}.{fext}"
        url = storage.upload_image(data, key, ct)
        image_urls.append(url)
        image_keys.append(key)

    with get_pool().connection() as conn:
        row = conn.execute(
            """
            INSERT INTO personas (id, nombre, ci, rol, estado, image_url, image_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING created_at
            """,
            (persona_id, nombre, ci, rol, estado, image_urls[0], image_keys[0]),
        ).fetchone()
        for url, key in zip(image_urls, image_keys):
            conn.execute(
                "INSERT INTO persona_images (persona_id, image_url, image_key) VALUES (%s, %s, %s)",
                (persona_id, url, key),
            )
        for emb, qual in all_embeddings:
            conn.execute(
                "INSERT INTO persona_embeddings (persona_id, embedding, calidad_rostro) VALUES (%s, %s, %s)",
                (persona_id, emb, qual),
            )
        conn.commit()

    return PersonaOut(
        id=str(persona_id), nombre=nombre, ci=ci, rol=rol,
        estado=estado, image_url=image_urls[0], created_at=row[0],
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
    parecidos. Para cada persona se usa su **mejor** embedding (mínima distancia)
    sin importar con cuántos ángulos fue registrada. `confianza` expresa el
    porcentaje de certeza y `es_match` marca los de alta confianza."""
    data = await file.read()
    try:
        embedding, _ = faces.embedding_from_bytes(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    s = get_settings()
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            WITH best AS (
                SELECT
                    pe.persona_id,
                    pe.embedding <=> %s AS distancia,
                    pe.calidad_rostro,
                    ROW_NUMBER() OVER (
                        PARTITION BY pe.persona_id
                        ORDER BY pe.embedding <=> %s ASC
                    ) AS rn
                FROM persona_embeddings pe
            )
            SELECT p.id, p.nombre, p.ci, p.rol, p.estado, p.image_url, p.created_at,
                   b.distancia, b.calidad_rostro
            FROM best b
            JOIN personas p ON p.id = b.persona_id
            WHERE b.rn = 1
            ORDER BY b.distancia ASC
            LIMIT %s
            """,
            (embedding, embedding, limite),
        ).fetchall()

    coincidencias = [
        Coincidencia(
            id=str(r[0]), nombre=r[1], ci=r[2], rol=r[3], estado=r[4],
            image_url=r[5], created_at=r[6], distancia=float(r[7]),
            confianza=faces.distance_to_confidence(float(r[7])),
            calidad_rostro=float(r[8]),
            es_match=float(r[7]) < s.match_threshold,
        )
        for r in rows
    ]
    return ResultadoBusqueda(umbral=s.match_threshold, coincidencias=coincidencias)


@app.post(
    "/personas/{persona_id}/fotos",
    response_model=FotosAgregadasOut,
    tags=["personas"],
    summary="Agregar fotos a una persona ya registrada",
    response_description="Cantidad de vectores faciales insertados.",
)
async def agregar_fotos(
    persona_id: str,
    files: list[UploadFile] = File(..., description="Una o más fotos adicionales del rostro (JPEG/PNG/WebP)."),
):
    """Agrega más fotos a una persona existente para mejorar la cobertura de ángulos.

    Útil cuando la primera búsqueda falla porque la foto de registro era muy frontal
    y la foto de búsqueda viene de un ángulo distinto. Cada foto genera hasta 3
    embeddings (base + rotaciones ±15°)."""
    try:
        pid = uuid.UUID(persona_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de persona inválido.")

    with get_pool().connection() as conn:
        if not conn.execute("SELECT 1 FROM personas WHERE id = %s", (pid,)).fetchone():
            raise HTTPException(status_code=404, detail="Persona no encontrada.")
        # Verificar límite total de fotos (máximo 3 por persona).
        current_count = conn.execute(
            "SELECT COUNT(*) FROM persona_images WHERE persona_id = %s", (pid,)
        ).fetchone()[0]
        if current_count + len(files) > 3:
            raise HTTPException(
                status_code=400,
                detail=f"Máximo 3 fotos por persona. Ya tiene {current_count}, intentas agregar {len(files)}.",
            )

    all_embeddings: list[tuple] = []
    uploaded_urls: list[str] = []
    for f in files:
        data = await f.read()
        ct = f.content_type or "image/jpeg"
        try:
            embs = faces.embeddings_from_bytes(data)
            all_embeddings.extend(embs)
            # Subir la foto al bucket.
            fext = CONTENT_EXT.get(ct, "jpg")
            key = f"personas/{pid}/{uuid.uuid4().hex[:8]}.{fext}"
            url = storage.upload_image(data, key, ct)
            uploaded_urls.append((url, key))
        except ValueError:
            pass  # Foto inútil — se omite.

    if not all_embeddings:
        raise HTTPException(status_code=400, detail="No se detectó ningún rostro en ninguna de las fotos enviadas.")

    with get_pool().connection() as conn:
        for url, key in uploaded_urls:
            conn.execute(
                "INSERT INTO persona_images (persona_id, image_url, image_key) VALUES (%s, %s, %s)",
                (pid, url, key),
            )
        for emb, qual in all_embeddings:
            conn.execute(
                "INSERT INTO persona_embeddings (persona_id, embedding, calidad_rostro) VALUES (%s, %s, %s)",
                (pid, emb, qual),
            )
        conn.commit()

    return FotosAgregadasOut(persona_id=persona_id, embeddings_agregados=len(all_embeddings))


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


@app.get(
    "/personas/{persona_id}/fotos",
    response_model=list[str],
    tags=["personas"],
    summary="Obtener todas las fotos de una persona",
    response_description="Lista de URLs de las fotos registradas.",
)
def obtener_fotos(persona_id: str):
    """Devuelve las URLs de todas las fotos subidas para esta persona.
    Se usa bajo demanda al abrir el detalle (modal) de un candidato."""
    try:
        pid = uuid.UUID(persona_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de persona inválido.")
    with get_pool().connection() as conn:
        if not conn.execute("SELECT 1 FROM personas WHERE id = %s", (pid,)).fetchone():
            raise HTTPException(status_code=404, detail="Persona no encontrada.")
        rows = conn.execute(
            "SELECT image_url FROM persona_images WHERE persona_id = %s ORDER BY created_at",
            (pid,),
        ).fetchall()
    return [r[0] for r in rows]
