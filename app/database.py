"""Conexión a Postgres + pgvector y esquema de tablas."""

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None


def _configure(conn: psycopg.Connection) -> None:
    # Registra el tipo `vector` en cada conexión nueva del pool.
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
    """Crea la extensión pgvector, las tablas y los índices si no existen.

    Usa una conexión directa (no del pool) porque la extensión `vector` debe
    existir antes de poder registrar su tipo en las conexiones del pool.
    También ejecuta migraciones automáticas al esquema multi-embedding.
    """
    s = get_settings()
    with psycopg.connect(s.database_url) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        register_vector(conn)

        # Tabla de personas: metadatos + foto principal (sin embedding — ver persona_embeddings).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS personas (
                id          UUID PRIMARY KEY,
                nombre      TEXT,
                ci          TEXT,
                rol         TEXT,
                estado      TEXT NOT NULL DEFAULT 'desaparecida',
                image_url   TEXT NOT NULL,
                image_key   TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        # Tabla de embeddings: múltiples vectores por persona (ángulos + augmentaciones).
        # Separarlos de `personas` permite registrar más fotos sin tocar los metadatos.
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS persona_embeddings (
                id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                persona_id     UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
                embedding      vector({s.embedding_dim}) NOT NULL,
                calidad_rostro FLOAT NOT NULL DEFAULT 1.0,
                etiqueta       TEXT,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        # Índice HNSW sobre los embeddings: búsqueda por distancia coseno rápida a escala.
        # HNSW no necesita entrenamiento previo (a diferencia de IVFFlat) y mantiene
        # alto recall incluso con pocos registros.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS persona_embeddings_hnsw "
            "ON persona_embeddings USING hnsw (embedding vector_cosine_ops)"
        )

        # Tabla de imágenes: todas las fotos subidas por persona (no solo la primera).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS persona_images (
                id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                persona_id UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
                image_url  TEXT NOT NULL,
                image_key  TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.commit()

        # Migración: si `personas` aún tiene la columna `embedding` del esquema antiguo
        # (SFace 128-dim), se elimina. Los embeddings buffalo_l 512-dim se registran de
        # nuevo a través de los endpoints normales.
        row = conn.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'personas' AND column_name = 'embedding'
            """
        ).fetchone()
        if row:
            conn.execute("ALTER TABLE personas DROP COLUMN embedding")
            conn.commit()
