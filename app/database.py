"""Conexión a Postgres + pgvector y esquema de las tablas.

Modelo de datos:
  - `personas`            -> una fila = una foto. Varias fotos de la misma persona
                             comparten `person_id`. Aquí viven los metadatos de dominio.
  - `persona_embeddings`  -> N vectores faciales por foto (base + augmentaciones por
                             rotación). El reconocimiento (InsightFace buffalo_l) compara
                             contra esta tabla y toma el mejor embedding por `person_id`.

`estado` distingue los dos flujos:
  - 'buscada'    -> la registró un FAMILIAR que busca a alguien.
  - 'encontrada' -> la registró un RESCATISTA que halló a alguien.
"""

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None

# Columnas extra del dominio (se agregan por ALTER para tablas ya existentes).
_EXTRA_COLS = [
    ("person_id", "UUID"),
    ("estado", "TEXT NOT NULL DEFAULT 'buscada'"),
    ("es_menor", "BOOLEAN NOT NULL DEFAULT false"),
    ("nombre", "TEXT"),
    ("apellido", "TEXT"),
    ("edad", "TEXT"),
    ("doc_tipo", "TEXT"),
    ("doc_numero", "TEXT"),
    ("telefono_contacto", "TEXT"),
    ("refugio", "TEXT"),
    ("telefono_responsable", "TEXT"),
    ("doc_responsable", "TEXT"),
    ("descripcion", "TEXT"),
    ("ubicacion", "TEXT"),
    ("codigo", "TEXT"),
    # Moderación: 'aprobada' (visible) | 'rechazada' (oculta) | 'pendiente'.
    ("moderacion", "TEXT NOT NULL DEFAULT 'aprobada'"),
]


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = ConnectionPool(s.database_url, configure=_configure, open=True)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def init_db() -> None:
    s = get_settings()
    with psycopg.connect(s.database_url, autocommit=True) as conn:
        # Lock: evita que varios workers choquen al crear extensión/tabla a la vez.
        conn.execute("SELECT pg_advisory_lock(927138)")
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)

        # --- Tabla de personas: metadatos + 1 fila por foto (sin embedding). ---
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS personas (
                id          UUID PRIMARY KEY,
                image_url   TEXT NOT NULL,
                image_key   TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Columnas del dominio (idempotente; actualiza tablas previas).
        for col, decl in _EXTRA_COLS:
            conn.execute(f"ALTER TABLE personas ADD COLUMN IF NOT EXISTS {col} {decl}")
        conn.execute("UPDATE personas SET person_id = id WHERE person_id IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS personas_person_id_idx ON personas (person_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS personas_estado_idx ON personas (estado)")

        # --- Migración del esquema antiguo (DeepFace/Facenet512) ---
        # Los embeddings vivían como columna en `personas`. Con InsightFace buffalo_l
        # los vectores no son comparables: se mueven a `persona_embeddings` y se elimina
        # la columna vieja junto a su índice. (Los datos viejos se recrean re-registrando.)
        conn.execute("DROP INDEX IF EXISTS personas_embedding_hnsw")
        conn.execute("ALTER TABLE personas DROP COLUMN IF EXISTS embedding")

        # --- Tabla de embeddings: N vectores por foto (base + rotaciones ±15°). ---
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS persona_embeddings (
                id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                foto_id        UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
                embedding      vector({s.embedding_dim}) NOT NULL,
                calidad_rostro FLOAT NOT NULL DEFAULT 1.0,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS persona_embeddings_foto_idx "
            "ON persona_embeddings (foto_id)"
        )
        # HNSW para búsqueda por distancia coseno rápida a escala (sin entrenamiento previo).
        conn.execute(
            "CREATE INDEX IF NOT EXISTS persona_embeddings_hnsw "
            "ON persona_embeddings USING hnsw (embedding vector_cosine_ops)"
        )

        # --- Reportes de usuarios: fallas de la página y publicaciones/fotos inadecuadas. ---
        # tipo='falla'       -> bug/problema de la web (descripcion + url opcional).
        # tipo='publicacion' -> contenido inadecuado de una publicación (person_id).
        # `person_id` no es FK porque en `personas` se repite (una fila por foto).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reportes (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tipo        TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                person_id   UUID,
                url         TEXT,
                contacto    TEXT,
                estado      TEXT NOT NULL DEFAULT 'pendiente',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS reportes_tipo_idx ON reportes (tipo)")
        conn.execute("CREATE INDEX IF NOT EXISTS reportes_estado_idx ON reportes (estado)")

        conn.execute("SELECT pg_advisory_unlock(927138)")
