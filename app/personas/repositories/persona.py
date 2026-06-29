"""Persona repository: all SQL for personas and persona_embeddings tables."""

import uuid
from contextlib import suppress
from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool

from app import storage
from app.domain.matching import MatchingPolicy
from app.domain.persona import PersonaBase

CONTENT_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _cols_with_alias(alias: str) -> str:
    """Column list with table alias prefix for search queries."""
    cols = (
        "person_id, estado, es_menor, nombre, apellido, edad, refugio, ubicacion, "
        "telefono_responsable, telefono_contacto, descripcion, encontrado_por, image_url"
    )
    return ", ".join(f"{alias}.{c.strip()}" for c in cols.split(","))


class PersonaRepository:
    """All SQL for the personas and persona_embeddings tables.
    No raw SQL for these tables remains in app/main.py.
    """

    # INSERT into personas (one row per photo)
    _INSERT_PERSONA = """
        INSERT INTO personas
          (id, person_id, estado, es_menor, nombre, apellido, edad, doc_tipo,
           doc_numero, telefono_contacto, refugio, telefono_responsable,
           doc_responsable, descripcion, ubicacion, codigo, encontrado_por,
           image_url, image_key)
        VALUES (%(id)s, %(pid)s, %(estado)s, %(menor)s, %(nombre)s, %(apellido)s, %(edad)s,
                %(doc_tipo)s, %(doc_numero)s, %(tel_contacto)s, %(refugio)s, %(tel_resp)s,
                %(doc_resp)s, %(descripcion)s, %(ubicacion)s, %(codigo)s, %(encontrado_por)s,
                %(url)s, %(key)s)
    """

    # INSERT into persona_embeddings (one row per embedding)
    _INSERT_EMBEDDING = """
        INSERT INTO persona_embeddings (foto_id, embedding, calidad_rostro)
        VALUES (%s, %s, %s)
    """

    # Search: best match per person via ROW_NUMBER() OVER (PARTITION BY ...)
    # Public: filters by moderacion='aprobada' and optionally estado
    _SEARCH = """
        SELECT {cols}, b.distancia
        FROM (
            SELECT pe.foto_id, p.person_id,
                   pe.embedding <=> %s AS distancia,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.person_id ORDER BY pe.embedding <=> %s ASC
                   ) AS rn
            FROM persona_embeddings pe
            JOIN personas p ON p.id = pe.foto_id
            WHERE p.moderacion = 'aprobada'
                {estado_filter}
        ) b
        JOIN personas p2 ON p2.id = b.foto_id
        WHERE b.rn = 1
        ORDER BY b.distancia ASC
        LIMIT %s OFFSET %s
    """

    _GET_BUSQUEDA_EMBEDDING = """
        SELECT pe.embedding
        FROM personas p
        JOIN persona_embeddings pe ON pe.foto_id = p.id
        WHERE p.codigo = %s AND p.estado = 'buscada'
        ORDER BY p.created_at ASC, pe.created_at ASC
        LIMIT 1
    """

    # Admin search: same ROW_NUMBER() but NO moderacion filter
    _SEARCH_ADMIN = """
        SELECT {cols}, b.distancia
        FROM (
            SELECT pe.foto_id, p.person_id,
                   pe.embedding <=> %s AS distancia,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.person_id ORDER BY pe.embedding <=> %s ASC
                   ) AS rn
            FROM persona_embeddings pe
            JOIN personas p ON p.id = pe.foto_id
                {estado_filter}
        ) b
        JOIN personas p2 ON p2.id = b.foto_id
        WHERE b.rn = 1
        ORDER BY b.distancia ASC
        LIMIT %s OFFSET %s
    """

    _COUNT_SEARCH_ADMIN = """
        SELECT count(DISTINCT p.person_id)
        FROM personas p
        JOIN persona_embeddings pe ON pe.foto_id = p.id
        WHERE 1 = 1
            {estado_filter}
    """

    # Admin list: aggregation with moderation column
    _LIST_ADMIN = """
        SELECT person_id, max(estado), bool_or(es_menor), max(nombre), max(apellido),
               max(edad), max(doc_numero), max(refugio), max(ubicacion),
               coalesce(max(telefono_responsable), max(telefono_contacto)),
               max(codigo), max(moderacion), array_agg(image_url), min(created_at)
        FROM personas {where}
        GROUP BY person_id ORDER BY min(created_at) DESC LIMIT %s OFFSET %s
    """

    # Listado PÚBLICO: una fila por persona, solo campos no sensibles, visibles (aprobada).
    _LIST_PUBLICO = """
        SELECT person_id, max(estado), bool_or(es_menor), max(nombre), max(apellido),
               max(edad), coalesce(max(refugio), max(ubicacion)) AS ubicacion,
               max(descripcion), (array_agg(image_url ORDER BY created_at))[1] AS image_url,
               min(created_at) AS created_at
        FROM personas
        WHERE estado = %s AND moderacion = 'aprobada'
        GROUP BY person_id
        ORDER BY min(created_at) DESC
        LIMIT %s OFFSET %s
    """

    # Conteos reales para el dashboard de admin (no dependen de paginación).
    _STATS_PERSONAS = """
        SELECT
          count(DISTINCT person_id)                                          AS total,
          count(DISTINCT person_id) FILTER (WHERE estado='buscada')          AS buscadas,
          count(DISTINCT person_id) FILTER (WHERE estado='encontrada')       AS encontradas,
          count(DISTINCT person_id) FILTER (WHERE es_menor)                  AS menores,
          count(DISTINCT person_id) FILTER (WHERE moderacion='rechazada')    AS ocultas,
          count(DISTINCT person_id) FILTER (WHERE moderacion='pendiente')    AS pendientes
        FROM personas
    """
    _STATS_REPORTES = """
        SELECT
          count(*) FILTER (WHERE tipo='publicacion')                              AS pub_total,
          count(*) FILTER (WHERE tipo='publicacion' AND estado='pendiente')       AS pub_pendientes,
          count(*) FILTER (WHERE tipo='falla')                                    AS fallas_total,
          count(*) FILTER (WHERE tipo='falla' AND estado='pendiente')             AS fallas_pendientes
        FROM reportes
    """

    # Update moderation status
    _SET_MODERACION = """
        UPDATE personas SET moderacion = %s WHERE person_id = %s
    """

    # Delete persona and (via ON DELETE CASCADE) embeddings
    _DELETE = """
        DELETE FROM personas WHERE person_id = %s
    """

    _SELECT_IMAGE_KEYS = """
        SELECT image_key FROM personas WHERE person_id = %s
    """

    # Match EXACTO por texto: cédula + nombre (+ apellido opcional), una fila por persona.
    # Comparación normalizada (trim + minúsculas). Solo personas visibles (aprobadas).
    _FIND_EXACT = """
        SELECT DISTINCT ON (p.person_id)
               p.person_id, p.estado, p.es_menor, p.nombre, p.apellido, p.edad,
               p.refugio, p.ubicacion, p.telefono_responsable, p.telefono_contacto,
               p.descripcion, p.encontrado_por, p.image_url
        FROM personas p
        WHERE p.estado = %s
          AND p.moderacion = 'aprobada'
          AND p.doc_numero IS NOT NULL AND lower(btrim(p.doc_numero)) = lower(btrim(%s))
          AND p.nombre IS NOT NULL AND lower(btrim(p.nombre)) = lower(btrim(%s))
          {apellido_filter}
        ORDER BY p.person_id, p.created_at ASC
        LIMIT 1
    """

    # Encontrada existente con la misma cédula (normalizada), una fila por persona.
    _FIND_BY_DOC = """
        SELECT DISTINCT ON (p.person_id)
               p.person_id, p.nombre, p.apellido, p.doc_numero, p.refugio,
               p.ubicacion, p.image_url, p.es_menor, p.codigo
        FROM personas p
        WHERE p.estado = 'encontrada'
          AND p.doc_numero IS NOT NULL AND lower(btrim(p.doc_numero)) = lower(btrim(%s))
        ORDER BY p.person_id, p.created_at ASC
        LIMIT 1
    """

    # ¿Existe esa persona? (cualquier fila/foto con ese person_id)
    _PERSONA_EXISTS = "SELECT 1 FROM personas WHERE person_id = %s LIMIT 1"

    # ¿Es VISIBLE? (al menos una fila aprobada). Para vistas públicas.
    _PERSONA_VISIBLE = (
        "SELECT 1 FROM personas WHERE person_id = %s AND moderacion = 'aprobada' LIMIT 1"
    )

    # Datos base de una persona por su person_id (una fila por persona).
    _PERSONA_BASICS = """
        SELECT person_id, max(doc_numero), max(estado), max(nombre), max(apellido)
        FROM personas WHERE person_id = %s GROUP BY person_id
    """

    # Búsqueda INVERSA: familiares (buscada, visibles) que buscan a alguien con esta
    # cédula. Una fila por familiar; trae su contacto para el reencuentro.
    _FIND_BUSCADAS_BY_DOC = """
        SELECT DISTINCT ON (p.person_id)
               p.person_id, p.nombre, p.apellido,
               coalesce(p.telefono_contacto, p.telefono_responsable) AS telefono,
               p.image_url, p.es_menor
        FROM personas p
        WHERE p.estado = 'buscada'
          AND p.moderacion = 'aprobada'
          AND p.doc_numero IS NOT NULL AND lower(btrim(p.doc_numero)) = lower(btrim(%s))
        ORDER BY p.person_id, p.created_at ASC
        LIMIT 50
    """

    # Inserta un evento de trazabilidad y devuelve sus campos.
    _INSERT_HISTORIAL = """
        INSERT INTO persona_historial
            (person_id, refugio, ubicacion, encontrado_por, telefono_responsable, nota)
        VALUES (%(pid)s, %(refugio)s, %(ubicacion)s, %(encontrado_por)s, %(tel)s, %(nota)s)
        RETURNING id, person_id, refugio, ubicacion, encontrado_por,
                  telefono_responsable, nota, created_at
    """

    # Actualiza los datos "actuales" de una persona encontrada (todas sus fotos).
    # COALESCE: solo pisa el valor si llega uno nuevo (no borra con NULL).
    _UPDATE_ENCONTRADA = """
        UPDATE personas SET
            refugio              = COALESCE(%(refugio)s, refugio),
            ubicacion            = COALESCE(%(ubicacion)s, ubicacion),
            encontrado_por       = COALESCE(%(encontrado_por)s, encontrado_por),
            telefono_responsable = COALESCE(%(tel)s, telefono_responsable)
        WHERE person_id = %(pid)s
    """

    _LIST_HISTORIAL = """
        SELECT id, person_id, refugio, ubicacion, encontrado_por,
               telefono_responsable, nota, created_at
        FROM persona_historial
        WHERE person_id = %s
        ORDER BY created_at ASC, id ASC
    """

    _COUNT_HISTORIAL = "SELECT count(*) FROM persona_historial WHERE person_id = %s"

    def __init__(self, pool: ConnectionPool, policy: MatchingPolicy):
        self._pool = pool
        self._policy = policy

    def add(
        self,
        person_id: UUID,
        persona: PersonaBase,
        procesadas: list[tuple[bytes, str, list[tuple[Any, float]]]],
    ) -> list[str]:
        """Insert one row per photo into personas + N embeddings per photo into persona_embeddings.

        Args:
            person_id: UUID grouping all photos.
            persona: PersonaBase domain object with all fields.
            procesadas: list of (image_data, content_type, [(embedding, calidad), ...]).

        Returns:
            List of uploaded image URLs.
        """
        urls = []
        with self._pool.connection() as conn:
            for data, ct, embs in procesadas:
                ext = CONTENT_EXT.get(ct, "jpg")
                foto_id = uuid.uuid4()
                key = f"personas/{foto_id}.{ext}"
                url = storage.upload_image(data, key, ct)

                # Map PersonaBase fields to SQL parameter names
                datos = {
                    "estado": persona.estado.value,
                    "menor": persona.es_menor,
                    "nombre": persona.nombre,
                    "apellido": persona.apellido,
                    "edad": persona.edad,
                    "doc_tipo": persona.doc_tipo,
                    "doc_numero": persona.doc_numero,
                    "tel_contacto": persona.telefono_contacto,
                    "refugio": persona.refugio,
                    "tel_resp": persona.telefono_responsable,
                    "doc_resp": persona.doc_responsable,
                    "descripcion": persona.descripcion,
                    "ubicacion": persona.ubicacion,
                    "codigo": persona.codigo,
                    "encontrado_por": persona.encontrado_por,
                    # SQL-specific fields
                    "id": foto_id,
                    "pid": person_id,
                    "url": url,
                    "key": key,
                }

                conn.execute(self._INSERT_PERSONA, datos)
                for emb, calidad in embs:
                    conn.execute(self._INSERT_EMBEDDING, (foto_id, emb, calidad))
                conn.commit()
                urls.append(url)
        return urls

    def search_by_estado(
        self, embedding: Any, estado: str | None, limit: int, offset: int = 0
    ) -> list[dict]:
        """Search personas by embedding, filtered by moderacion='aprobada'.

        Uses ROW_NUMBER() OVER (PARTITION BY p.person_id ORDER BY pe.embedding <=> %s ASC)
        to get the best match per person across all embeddings. Soporta paginación (offset).

        Returns list of Candidato-shaped dicts with distancia, coincidencia, confianza.
        Does NOT apply privacy masking (call MenoresPrivacy at the endpoint level).
        """
        cols = _cols_with_alias("p2")
        estado_filter = "AND p.estado = %s" if estado else ""
        params: tuple = (embedding, embedding)
        if estado:
            params = params + (estado,)
        params = params + (limit, max(0, offset))
        sql = self._SEARCH.format(cols=cols, estado_filter=estado_filter)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_candidato_dict(r) for r in rows]

    def find_exact_match(
        self,
        *,
        doc_numero: str,
        nombre: str,
        apellido: str | None = None,
        estado: str = "encontrada",
    ) -> dict | None:
        """Busca un match EXACTO por texto entre los `estado` visibles (aprobados).

        Coincidencia TOTAL de cédula + nombre (y apellido si se aporta), normalizada
        (trim + minúsculas). Pensada como atajo: si hay match textual exacto no hace
        falta la búsqueda por imagen.

        Devuelve un dict con forma de Candidato (distancia=0.0, coincidencia=100,
        confianza='alta') o None si no hay coincidencia textual total. No aplica
        privacidad de menores (se aplica a nivel de uso/endpoint).
        """
        ap = apellido.strip() if apellido else ""
        apellido_filter = (
            "AND p.apellido IS NOT NULL AND lower(btrim(p.apellido)) = lower(btrim(%s))"
            if ap
            else ""
        )
        params: tuple = (estado, doc_numero, nombre)
        if ap:
            params = params + (ap,)
        sql = self._FIND_EXACT.format(apellido_filter=apellido_filter)
        with self._pool.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return self._exact_row_to_candidato_dict(row)

    def find_encontrada_by_doc(self, doc_numero: str) -> dict | None:
        """Devuelve la persona ENCONTRADA cuya cédula coincide (normalizada), o None.

        Sirve para detectar duplicados al registrar un encontrado. No filtra por
        moderación: un duplicado pendiente sigue siendo duplicado.
        """
        if not doc_numero or not doc_numero.strip():
            return None
        with self._pool.connection() as conn:
            row = conn.execute(self._FIND_BY_DOC, (doc_numero,)).fetchone()
        if row is None:
            return None
        return {
            "person_id": str(row[0]),
            "nombre": row[1],
            "apellido": row[2],
            "doc_numero": row[3],
            "refugio": row[4],
            "ubicacion": row[5],
            "image_url": row[6],
            "es_menor": bool(row[7]),
            "codigo": row[8],
        }

    def persona_exists(self, person_id: str) -> bool:
        """True si existe alguna foto/fila con ese person_id."""
        with self._pool.connection() as conn:
            return conn.execute(self._PERSONA_EXISTS, (person_id,)).fetchone() is not None

    def persona_visible(self, person_id: str) -> bool:
        """True si la persona existe y está VISIBLE (moderacion='aprobada')."""
        with self._pool.connection() as conn:
            return conn.execute(self._PERSONA_VISIBLE, (person_id,)).fetchone() is not None

    def get_persona_basics(self, person_id: str) -> dict | None:
        """Datos base de una persona (doc/estado/nombre) o None si no existe."""
        with self._pool.connection() as conn:
            row = conn.execute(self._PERSONA_BASICS, (person_id,)).fetchone()
        if row is None:
            return None
        return {
            "person_id": str(row[0]),
            "doc_numero": row[1],
            "estado": row[2],
            "nombre": row[3],
            "apellido": row[4],
        }

    def find_buscadas_by_doc(self, doc_numero: str) -> list[dict]:
        """Búsqueda INVERSA: familiares (buscada visibles) que buscan esta cédula.

        Devuelve una lista de dicts con el contacto del familiar para el reencuentro.
        Lista vacía si nadie la buscaba o no se aporta cédula. No aplica privacidad
        de menores (se aplica al construir la alerta).
        """
        if not doc_numero or not doc_numero.strip():
            return []
        with self._pool.connection() as conn:
            rows = conn.execute(self._FIND_BUSCADAS_BY_DOC, (doc_numero,)).fetchall()
        return [
            {
                "person_id": str(r[0]),
                "nombre": r[1],
                "apellido": r[2],
                "telefono": r[3],
                "image_url": r[4],
                "es_menor": bool(r[5]),
            }
            for r in rows
        ]

    def add_historial(
        self,
        person_id: str,
        *,
        refugio: str | None = None,
        ubicacion: str | None = None,
        encontrado_por: str | None = None,
        telefono_responsable: str | None = None,
        nota: str | None = None,
        actualizar_actual: bool = True,
    ) -> dict:
        """Agrega un evento al histórico de trazabilidad y devuelve el evento creado.

        Si `actualizar_actual` (por defecto), también actualiza los datos "actuales"
        de la persona (refugio/ubicacion/encontrado_por/teléfono) — así la ficha
        refleja el último avistamiento mientras el histórico conserva todos.
        """
        params = {
            "pid": person_id,
            "refugio": refugio,
            "ubicacion": ubicacion,
            "encontrado_por": encontrado_por,
            "tel": telefono_responsable,
            "nota": nota,
        }
        with self._pool.connection() as conn:
            row = conn.execute(self._INSERT_HISTORIAL, params).fetchone()
            if actualizar_actual:
                conn.execute(self._UPDATE_ENCONTRADA, params)
            conn.commit()
        return self._historial_row_to_dict(row)

    def list_historial(self, person_id: str) -> list[dict]:
        """Histórico de trazabilidad de una persona, en orden cronológico."""
        with self._pool.connection() as conn:
            rows = conn.execute(self._LIST_HISTORIAL, (person_id,)).fetchall()
        return [self._historial_row_to_dict(r) for r in rows]

    def count_historial(self, person_id: str) -> int:
        """Cantidad de eventos en el histórico de una persona."""
        with self._pool.connection() as conn:
            return int(conn.execute(self._COUNT_HISTORIAL, (person_id,)).fetchone()[0])

    def get_busqueda_embedding(self, codigo: str) -> Any | None:
        """Return the stored query embedding for a FAMILIAR search code."""
        with self._pool.connection() as conn:
            row = conn.execute(self._GET_BUSQUEDA_EMBEDDING, (codigo,)).fetchone()
        return row[0] if row else None

    def list_publico(self, estado: str, limit: int, offset: int = 0) -> list[dict]:
        """Listado PÚBLICO paginado (sin datos sensibles). Solo moderacion='aprobada'."""
        with self._pool.connection() as conn:
            rows = conn.execute(self._LIST_PUBLICO, (estado, limit, max(0, offset))).fetchall()
        return [
            {
                "person_id": str(r[0]),
                "estado": r[1],
                "es_menor": bool(r[2]),
                "nombre": r[3],
                "apellido": r[4],
                "edad": r[5],
                "ubicacion": r[6],
                "descripcion": r[7],
                "image_url": r[8],
                "created_at": r[9],
            }
            for r in rows
        ]

    def count_aprobadas(self, estado: str | None = None) -> int:
        """Cuenta personas únicas visibles (moderacion='aprobada'), opcional por estado.

        Es el universo de candidatos de una búsqueda → total_records para paginar /buscados.
        """
        sql = (
            "SELECT count(DISTINCT person_id) FROM personas WHERE moderacion='aprobada'"
        )
        params: tuple = ()
        if estado in ("buscada", "encontrada"):
            sql += " AND estado = %s"
            params = (estado,)
        with self._pool.connection() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def count_admin(
        self,
        estado: str | None = None,
        moderacion: str | None = None,
        nombre: str | None = None,
        apellido: str | None = None,
        cedula: str | None = None,
        es_menor: bool | None = None,
    ) -> int:
        """Cuenta personas únicas con los mismos filtros que `list_admin` (para meta)."""
        conds, args = self._build_admin_filters(
            estado=estado,
            moderacion=moderacion,
            nombre=nombre,
            apellido=apellido,
            cedula=cedula,
            es_menor=es_menor,
        )
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        sql = f"SELECT count(DISTINCT person_id) FROM personas {where}"
        with self._pool.connection() as conn:
            return int(conn.execute(sql, tuple(args)).fetchone()[0])

    @staticmethod
    def _build_admin_filters(
        *,
        estado: str | None = None,
        moderacion: str | None = None,
        nombre: str | None = None,
        apellido: str | None = None,
        cedula: str | None = None,
        es_menor: bool | None = None,
    ) -> tuple[list[str], list[object]]:
        """Build shared WHERE filters for admin personas list and count."""
        conds: list[str] = []
        args: list[object] = []
        if estado in ("buscada", "encontrada"):
            conds.append("estado = %s")
            args.append(estado)
        if moderacion in ("aprobada", "rechazada", "pendiente"):
            conds.append("moderacion = %s")
            args.append(moderacion)
        if nombre and nombre.strip():
            conds.append("nombre ILIKE %s")
            args.append(f"%{nombre.strip()}%")
        if apellido and apellido.strip():
            conds.append("apellido ILIKE %s")
            args.append(f"%{apellido.strip()}%")
        if cedula and cedula.strip():
            conds.append("doc_numero ILIKE %s")
            args.append(f"%{cedula.strip()}%")
        if es_menor is not None:
            conds.append("es_menor = %s")
            args.append(es_menor)
        return conds, args

    def count_search_admin(self, estado: str | None = None) -> int:
        """Count admin-searchable personas with embeddings for pagination metadata."""
        estado_filter = "AND p.estado = %s" if estado else ""
        params: tuple = (estado,) if estado_filter else ()
        sql = self._COUNT_SEARCH_ADMIN.format(estado_filter=estado_filter)
        with self._pool.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def search_admin(
        self, embedding: Any, estado: str | None, limit: int, offset: int = 0
    ) -> list[dict]:
        """Admin search: same as search_by_estado but NO moderacion filter.

        Returns list of Candidato-shaped dicts. Does NOT apply privacy masking.
        """
        cols = _cols_with_alias("p2")
        estado_filter = "AND p.estado = %s" if estado else ""
        params: tuple = (embedding, embedding)
        if estado:
            params = params + (estado,)
        params = params + (limit, max(0, offset))
        sql = self._SEARCH_ADMIN.format(cols=cols, estado_filter=estado_filter)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_candidato_dict(r) for r in rows]

    def list_admin(
        self,
        limit: int,
        estado: str | None = None,
        moderacion: str | None = None,
        offset: int = 0,
        nombre: str | None = None,
        apellido: str | None = None,
        cedula: str | None = None,
        es_menor: bool | None = None,
    ) -> list[dict]:
        """List personas for admin view, with optional estado/moderacion filters.

        Soporta paginación con `offset`. Returns list of PersonaAdmin-shaped dicts.
        Does NOT apply privacy masking.
        """
        conds, args = self._build_admin_filters(
            estado=estado,
            moderacion=moderacion,
            nombre=nombre,
            apellido=apellido,
            cedula=cedula,
            es_menor=es_menor,
        )
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        args.append(limit)
        args.append(max(0, offset))
        sql = self._LIST_ADMIN.format(where=where)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [self._row_to_admin_dict(r) for r in rows]

    def stats(self) -> dict:
        """Conteos reales (totales) para el dashboard de admin. No paginado."""
        with self._pool.connection() as conn:
            p = conn.execute(self._STATS_PERSONAS).fetchone()
            r = conn.execute(self._STATS_REPORTES).fetchone()
        return {
            "total": p[0],
            "buscadas": p[1],
            "encontradas": p[2],
            "menores": p[3],
            "ocultas": p[4],
            "pendientes_moderacion": p[5],
            "reportes_publicaciones": r[0],
            "reportes_publicaciones_pendientes": r[1],
            "reportes_fallas": r[2],
            "reportes_fallas_pendientes": r[3],
        }

    def set_moderacion(self, person_id: str, valor: str) -> int:
        """Update moderacion for all rows with the given person_id.

        Returns number of rows updated.
        """
        with self._pool.connection() as conn:
            n = conn.execute(self._SET_MODERACION, (valor, person_id)).rowcount
            conn.commit()
        return n

    def delete(self, person_id: str) -> int:
        """Delete persona (and embeddings via ON DELETE CASCADE).

        Also removes images from storage. Returns number of photos deleted.
        """
        with self._pool.connection() as conn:
            rows = conn.execute(self._SELECT_IMAGE_KEYS, (person_id,)).fetchall()
            if not rows:
                return 0
            keys = [r[0] for r in rows]
            conn.execute(self._DELETE, (person_id,))
            conn.commit()
        for key in keys:
            with suppress(Exception):
                storage.delete_image(key)  # best-effort cleanup
        return len(keys)

    def _row_to_candidato_dict(self, row: tuple) -> dict:
        """Convert one SQL row from search queries into a Candidato-shaped dict."""
        (
            person_id,
            estado,
            es_menor,
            nombre,
            apellido,
            edad,
            refugio,
            ubicacion,
            tel_resp,
            tel_contacto,
            descripcion,
            encontrado_por,
            image_url,
            distancia,
        ) = row
        d = float(distancia)
        return {
            "person_id": str(person_id),
            "estado": estado,
            "es_menor": bool(es_menor),
            "nombre": nombre,
            "apellido": apellido,
            "edad": edad,
            "refugio": refugio,
            "ubicacion": ubicacion or refugio,
            "telefono": tel_resp or tel_contacto,
            "encontrado_por": encontrado_por,
            "descripcion": descripcion,
            "image_url": image_url,
            "distancia": round(d, 4),
            "coincidencia": self._policy.match_percentage(d),
            "confianza": self._policy.confidence_band(d),
        }

    def _historial_row_to_dict(self, row: tuple) -> dict:
        """Convierte una fila de persona_historial en un EventoHistorial-shaped dict."""
        (id_, person_id, refugio, ubicacion, encontrado_por, tel, nota, created_at) = row
        return {
            "id": str(id_),
            "person_id": str(person_id),
            "refugio": refugio,
            "ubicacion": ubicacion,
            "encontrado_por": encontrado_por,
            "telefono_responsable": tel,
            "nota": nota,
            "created_at": created_at,
        }

    def _exact_row_to_candidato_dict(self, row: tuple) -> dict:
        """Candidato dict para un match EXACTO por texto: 100% sin pasar por el sigmoid."""
        (
            person_id,
            estado,
            es_menor,
            nombre,
            apellido,
            edad,
            refugio,
            ubicacion,
            tel_resp,
            tel_contacto,
            descripcion,
            encontrado_por,
            image_url,
        ) = row
        return {
            "person_id": str(person_id),
            "estado": estado,
            "es_menor": bool(es_menor),
            "nombre": nombre,
            "apellido": apellido,
            "edad": edad,
            "refugio": refugio,
            "ubicacion": ubicacion or refugio,
            "telefono": tel_resp or tel_contacto,
            "encontrado_por": encontrado_por,
            "descripcion": descripcion,
            "image_url": image_url,
            "distancia": 0.0,
            "coincidencia": 100,
            "confianza": "alta",
        }

    def _row_to_admin_dict(self, row: tuple) -> dict:
        """Convert one admin aggregation row into a PersonaAdmin-shaped dict."""
        (
            person_id,
            estado,
            es_menor,
            nombre,
            apellido,
            edad,
            doc,
            refugio,
            ubicacion,
            telefono,
            codigo,
            moderacion,
            fotos,
            created_at,
        ) = row
        return {
            "person_id": str(person_id),
            "estado": estado,
            "es_menor": bool(es_menor),
            "nombre": nombre,
            "apellido": apellido,
            "edad": edad,
            "doc": doc,
            "refugio": refugio,
            "ubicacion": ubicacion,
            "telefono": telefono,
            "codigo": codigo,
            "moderacion": moderacion,
            "fotos": list(fotos),
            "created_at": created_at,
        }
