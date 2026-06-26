"""Conexión a Postgres + pgvector y esquema de la tabla de personas."""

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
    """Crea la extensión pgvector, la tabla y el índice si no existen.

    Usa una conexión directa (no del pool) porque la extensión `vector` debe
    existir antes de poder registrar su tipo en las conexiones del pool.
    """
    s = get_settings()
    with psycopg.connect(s.database_url) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        register_vector(conn)
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS personas (
                id          UUID PRIMARY KEY,
                nombre      TEXT,
                ci          TEXT,
                rol         TEXT,
                estado      TEXT NOT NULL DEFAULT 'desaparecida',
                image_url   TEXT NOT NULL,
                image_key   TEXT NOT NULL,
                embedding   vector({s.embedding_dim}) NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Índice HNSW para búsqueda vectorial rápida a escala (miles/millones de
        # caras). A diferencia de ivfflat, HNSW da resultados correctos también con
        # pocos registros (no necesita "entrenamiento") y mantiene alto recall.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS personas_embedding_hnsw "
            "ON personas USING hnsw (embedding vector_cosine_ops)"
        )
        conn.commit()
