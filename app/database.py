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
    ("encontrado_por", "TEXT"),  # nombre de quien encontró a la persona
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS personas_person_id_idx ON personas (person_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS personas_estado_idx ON personas (estado)"
        )

        # --- Migración del esquema antiguo (DeepFace/Facenet512) ---
        # Los embeddings vivían como columna en `personas`. Con InsightFace buffalo_l
        # los vectores no son comparables: se mueven a `persona_embeddings` y se elimina
        # la columna vieja junto a su índice. (Los datos viejos se recrean re-registrando.)
        conn.execute("DROP INDEX IF EXISTS personas_embedding_hnsw")
        conn.execute("ALTER TABLE personas DROP COLUMN IF EXISTS embedding")

        # --- Tabla de embeddings: N vectores por foto (base + rotaciones ±15°). ---
        # Migración: si la tabla ya existe pero con dimensión distinta, la recreamos.
        _embedding_col_type = f"vector({s.embedding_dim})"
        _row = conn.execute(
            "SELECT column_name, udt_name, character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_name='persona_embeddings' AND column_name='embedding'"
        ).fetchone()
        if _row is not None:
            _current_dim = _row[2]
            if _current_dim != s.embedding_dim:
                conn.execute("DROP TABLE IF EXISTS persona_embeddings CASCADE")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS persona_embeddings (
                id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                foto_id        UUID NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
                embedding      {_embedding_col_type} NOT NULL,
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

        # --- Trazabilidad: histórico de avistamientos de una persona ENCONTRADA. ---
        # Cada fila = un evento (un rescatista la vio/registró en un lugar y momento).
        # El registro inicial crea el primer evento; cada vez que un rescatista reporta
        # de nuevo a la misma persona (misma cédula) o modifica su ubicación, se agrega
        # otro evento con su timestamp. Así queda el rastro de dónde estuvo y cuándo.
        # `person_id` no es FK porque en `personas` se repite (una fila por foto).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS persona_historial (
                id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                person_id            UUID NOT NULL,
                refugio              TEXT,
                ubicacion            TEXT,
                encontrado_por       TEXT,
                telefono_responsable TEXT,
                nota                 TEXT,
                created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS persona_historial_person_idx "
            "ON persona_historial (person_id)"
        )

        # --- Tabla de admins (superadmin) ---
        # El password NUNCA se guarda en plano: vive como hash bcrypt. El seed inicial
        # (desde env vars) lo crea la primera vez que init_db() corre con la tabla
        # vacía — ver main.lifespan.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_active     BOOLEAN NOT NULL DEFAULT true,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_login_at TIMESTAMPTZ
            )
            """
        )

        # --- Tabla de testimonios: fotos/videos de reencuentro. ---
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS testimonios (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                person_id       UUID,
                tipo            TEXT NOT NULL,
                archivo_url     TEXT NOT NULL,
                archivo_key     TEXT NOT NULL,
                mime            TEXT NOT NULL,
                bytes           INTEGER NOT NULL,
                mensaje         TEXT,
                nombre_testigo  TEXT,
                contacto_testigo TEXT,
                estado          TEXT NOT NULL DEFAULT 'pendiente',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS testimonios_person_id_idx "
            "ON testimonios (person_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS testimonios_estado_idx "
            "ON testimonios (estado)"
        )

        conn.execute("SELECT pg_advisory_unlock(927138)")
