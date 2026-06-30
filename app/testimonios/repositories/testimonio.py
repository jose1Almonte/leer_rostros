"""Testimonio repository — all SQL for the testimonios table."""

import uuid
from uuid import UUID

from psycopg_pool import ConnectionPool


class TestimonioRepository:
    """All SQL for the `testimonios` table.

    Testimonios are photo/video uploads from people who found a match,
    optionally linked to a person_id.
    """

    _ESTADOS = ("pendiente", "aprobada", "rechazada")

    _INSERT = """
        INSERT INTO testimonios (id, person_id, tipo, archivo_url, archivo_key,
                                 mime, bytes, mensaje, nombre_testigo, contacto_testigo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, person_id, tipo, estado, created_at
    """

    _SELECT_PERSONA_EXISTS = """
        SELECT 1 FROM personas WHERE person_id = %s LIMIT 1
    """

    _SELECT_BY_PERSON = """
        SELECT id, person_id, tipo, archivo_url, mensaje, nombre_testigo, created_at
        FROM testimonios
        WHERE person_id = %s AND estado = 'aprobada'
        ORDER BY created_at DESC
    """

    _SELECT_ALL_APROBADOS = """
        SELECT id, person_id, tipo, archivo_url, mensaje, nombre_testigo, created_at
        FROM testimonios
        WHERE estado = 'aprobada'
        ORDER BY created_at DESC
        LIMIT %s
    """

    _LIST_ADMIN = """
        SELECT t.id, t.person_id, t.tipo, t.archivo_url, t.mime, t.bytes,
               t.mensaje, t.nombre_testigo, t.contacto_testigo, t.estado, t.created_at,
               p.nombre, p.estado, p.image_url
        FROM testimonios t
        LEFT JOIN LATERAL (
            SELECT nombre, estado, image_url FROM personas
            WHERE person_id = t.person_id ORDER BY created_at LIMIT 1
        ) p ON true
        {where}
        ORDER BY t.created_at DESC LIMIT %s
    """

    _GET_BY_ID = """
        SELECT id, person_id, tipo, archivo_url, archivo_key, mime, bytes,
               mensaje, nombre_testigo, contacto_testigo, estado, created_at
        FROM testimonios WHERE id = %s
    """

    _SET_ESTADO = """
        UPDATE testimonios SET estado = %s WHERE id = %s
    """

    _DELETE = """
        DELETE FROM testimonios WHERE id = %s
    """

    _COUNT_PENDIENTES = """
        SELECT count(*) FROM testimonios WHERE estado = 'pendiente'
    """

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def add(
        self,
        *,
        person_id: UUID | None,
        tipo: str,
        archivo_url: str,
        archivo_key: str,
        mime: str,
        bytes: int,
        mensaje: str | None,
        nombre_testigo: str | None,
        contacto_testigo: str | None,
    ) -> dict:
        with self._pool.connection() as conn:
            row = conn.execute(
                self._INSERT,
                (
                    uuid.uuid4(),
                    person_id,
                    tipo,
                    archivo_url,
                    archivo_key,
                    mime,
                    bytes,
                    mensaje,
                    nombre_testigo,
                    contacto_testigo,
                ),
            ).fetchone()
            conn.commit()
        assert row is not None
        return {
            "id": str(row[0]),
            "person_id": str(row[1]) if row[1] else None,
            "tipo": row[2],
            "estado": row[3],
            "created_at": row[4],
        }

    def persona_exists(self, person_id: UUID) -> bool:
        """Return True if any row in `personas` matches the given person_id."""
        with self._pool.connection() as conn:
            r = conn.execute(self._SELECT_PERSONA_EXISTS, (person_id,)).fetchone()
        return r is not None

    def list_by_person(self, person_id: UUID) -> list[dict]:
        """Return approved testimonios for a given person_id, newest first."""
        with self._pool.connection() as conn:
            rows = conn.execute(self._SELECT_BY_PERSON, (person_id,)).fetchall()
        return [self._row_to_publico(r) for r in rows]

    def list_all_aprobados(self, limite: int = 50) -> list[dict]:
        """Return all approved testimonios, newest first, with person_id."""
        with self._pool.connection() as conn:
            rows = conn.execute(self._SELECT_ALL_APROBADOS, (limite,)).fetchall()
        return [self._row_to_publico(r) for r in rows]

    def list_admin(
        self, estado: str | None = None, limite: int = 100
    ) -> list[dict]:
        """List testimonios for admin view, optionally filtered by estado."""
        conds, args = [], []
        if estado in self._ESTADOS:
            conds.append("t.estado = %s")
            args.append(estado)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        args.append(limite)
        sql = self._LIST_ADMIN.format(where=where)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [self._row_to_admin(r) for r in rows]

    def get(self, id: UUID) -> dict | None:
        with self._pool.connection() as conn:
            row = conn.execute(self._GET_BY_ID, (id,)).fetchone()
        if row is None:
            return None
        return self._row_to_full(row)

    def set_estado(self, id: UUID, estado: str) -> int:
        with self._pool.connection() as conn:
            n = conn.execute(self._SET_ESTADO, (estado, id)).rowcount
            conn.commit()
        return n

    def delete(self, id: UUID) -> dict | None:
        """Delete testimonio row and return the archivo_key for storage cleanup."""
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT archivo_key FROM testimonios WHERE id = %s", (id,)
            ).fetchone()
            if row is None:
                return None
            key = row[0]
            conn.execute(self._DELETE, (id,))
            conn.commit()
        return {"archivo_key": key}

    def count_pendientes(self) -> int:
        with self._pool.connection() as conn:
            r = conn.execute(self._COUNT_PENDIENTES).fetchone()
        return r[0] if r else 0

    @staticmethod
    def _row_to_publico(row: tuple) -> dict:
        return {
            "id": str(row[0]),
            "person_id": str(row[1]) if row[1] else None,
            "tipo": row[2],
            "archivo_url": row[3],
            "mensaje": row[4],
            "nombre_testigo": row[5],
            "created_at": row[6],
        }

    @staticmethod
    def _row_to_admin(row: tuple) -> dict:
        (
            tid, person_id, tipo, archivo_url, mime, bytes_,
            mensaje, nombre, contacto, estado, created_at,
            pub_nombre, pub_estado, pub_image_url,
        ) = row
        return {
            "id": str(tid),
            "person_id": str(person_id) if person_id else None,
            "tipo": tipo,
            "archivo_url": archivo_url,
            "mime": mime,
            "bytes": bytes_,
            "mensaje": mensaje,
            "nombre_testigo": nombre,
            "contacto_testigo": contacto,
            "estado": estado,
            "created_at": created_at,
            "pub_nombre": pub_nombre,
            "pub_estado": pub_estado,
            "pub_image_url": pub_image_url,
        }

    @staticmethod
    def _row_to_full(row: tuple) -> dict:
        (
            tid, person_id, tipo, archivo_url, archivo_key, mime, bytes_,
            mensaje, nombre, contacto, estado, created_at,
        ) = row
        return {
            "id": str(tid),
            "person_id": str(person_id) if person_id else None,
            "tipo": tipo,
            "archivo_url": archivo_url,
            "archivo_key": archivo_key,
            "mime": mime,
            "bytes": bytes_,
            "mensaje": mensaje,
            "nombre_testigo": nombre,
            "contacto_testigo": contacto,
            "estado": estado,
            "created_at": created_at,
        }
