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
        "telefono_responsable, telefono_contacto, descripcion, image_url"
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
           doc_responsable, descripcion, ubicacion, codigo, image_url, image_key)
        VALUES (%(id)s, %(pid)s, %(estado)s, %(menor)s, %(nombre)s, %(apellido)s, %(edad)s,
                %(doc_tipo)s, %(doc_numero)s, %(tel_contacto)s, %(refugio)s, %(tel_resp)s,
                %(doc_resp)s, %(descripcion)s, %(ubicacion)s, %(codigo)s, %(url)s, %(key)s)
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
        LIMIT %s
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
        LIMIT %s
    """

    # Admin list: aggregation with moderation column
    _LIST_ADMIN = """
        SELECT person_id, max(estado), bool_or(es_menor), max(nombre), max(apellido),
               max(edad), max(doc_numero), max(refugio), max(ubicacion),
               coalesce(max(telefono_responsable), max(telefono_contacto)),
               max(codigo), max(moderacion), array_agg(image_url), min(created_at)
        FROM personas {where}
        GROUP BY person_id ORDER BY min(created_at) DESC LIMIT %s
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
        self, embedding: Any, estado: str | None, limit: int
    ) -> list[dict]:
        """Search personas by embedding, filtered by moderacion='aprobada'.

        Uses ROW_NUMBER() OVER (PARTITION BY p.person_id ORDER BY pe.embedding <=> %s ASC)
        to get the best match per person across all embeddings.

        Returns list of Candidato-shaped dicts with distancia, coincidencia, confianza.
        Does NOT apply privacy masking (call MenoresPrivacy at the endpoint level).
        """
        cols = _cols_with_alias("p2")
        estado_filter = "AND p.estado = %s" if estado else ""
        params: tuple = (embedding, embedding)
        if estado:
            params = params + (estado,)
        params = params + (limit,)
        sql = self._SEARCH.format(cols=cols, estado_filter=estado_filter)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_candidato_dict(r) for r in rows]

    def search_admin(
        self, embedding: Any, estado: str | None, limit: int
    ) -> list[dict]:
        """Admin search: same as search_by_estado but NO moderacion filter.

        Returns list of Candidato-shaped dicts. Does NOT apply privacy masking.
        """
        cols = _cols_with_alias("p2")
        estado_filter = "AND p.estado = %s" if estado else ""
        params: tuple = (embedding, embedding)
        if estado:
            params = params + (estado,)
        params = params + (limit,)
        sql = self._SEARCH_ADMIN.format(cols=cols, estado_filter=estado_filter)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_candidato_dict(r) for r in rows]

    def list_admin(
        self, limit: int, estado: str | None = None, moderacion: str | None = None
    ) -> list[dict]:
        """List personas for admin view, with optional estado/moderacion filters.

        Returns list of PersonaAdmin-shaped dicts. Does NOT apply privacy masking.
        """
        conds, args = [], []
        if estado in ("buscada", "encontrada"):
            conds.append("estado = %s")
            args.append(estado)
        if moderacion in ("aprobada", "rechazada", "pendiente"):
            conds.append("moderacion = %s")
            args.append(moderacion)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        args.append(limit)
        sql = self._LIST_ADMIN.format(where=where)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [self._row_to_admin_dict(r) for r in rows]

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
            "descripcion": descripcion,
            "image_url": image_url,
            "distancia": round(d, 4),
            "coincidencia": self._policy.match_percentage(d),
            "confianza": self._policy.confidence_band(d),
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
