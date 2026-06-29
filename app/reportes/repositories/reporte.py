"""Reporte repository: all SQL for the reportes table."""

import uuid
from uuid import UUID

from psycopg_pool import ConnectionPool


class ReporteRepository:
    """All SQL for the `reportes` table.

    Reports cover two flows:
    - tipo='falla'       — bug reports about the website (no person_id).
    - tipo='publicacion' — reports about an inadequate publication (has person_id).

    The `person_id` is NOT a foreign key because `personas` has one row per photo
    (multiple rows share the same person_id). Existence is checked explicitly in
    `RegistrarPublicacion` before inserting a report.
    """

    _ESTADOS = ("pendiente", "revisado", "resuelto", "descartado")
    _TIPOS = ("falla", "publicacion")

    _INSERT = """
        INSERT INTO reportes (tipo, descripcion, person_id, url, contacto)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, tipo, estado, created_at
    """

    _SELECT_PERSONA_EXISTS = """
        SELECT 1 FROM personas WHERE person_id = %s LIMIT 1
    """

    _LIST_ADMIN = """
        SELECT r.id, r.tipo, r.descripcion, r.estado, r.person_id, r.url, r.contacto,
               r.created_at, p.nombre, p.estado, p.image_url, p.moderacion
        FROM reportes r
        LEFT JOIN LATERAL (
            SELECT nombre, estado, image_url, moderacion FROM personas
            WHERE person_id = r.person_id ORDER BY created_at LIMIT 1
        ) p ON true
        {where}
        ORDER BY r.created_at DESC LIMIT %s OFFSET %s
    """

    _COUNT_ADMIN = """
        SELECT count(*)
        FROM reportes r
        {where}
    """

    _UPDATE_ESTADO = """
        UPDATE reportes SET estado = %s WHERE id = %s
    """

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def add_falla(
        self,
        *,
        descripcion: str,
        url: str | None,
        contacto: str | None,
    ) -> dict:
        """Insert a `falla` report. Returns a ReporteCreado-shaped dict."""
        with self._pool.connection() as conn:
            row = conn.execute(
                self._INSERT, ("falla", descripcion, None, url, contacto)
            ).fetchone()
            conn.commit()
        assert row is not None
        return {
            "id": str(row[0]),
            "tipo": row[1],
            "estado": row[2],
            "created_at": row[3],
        }

    def add_publicacion(
        self,
        *,
        descripcion: str,
        person_id: UUID,
        contacto: str | None,
    ) -> dict:
        """Insert a `publicacion` report. Caller must verify the person_id exists
        (use `persona_exists`) before calling this."""
        with self._pool.connection() as conn:
            row = conn.execute(
                self._INSERT,
                ("publicacion", descripcion, person_id, None, contacto),
            ).fetchone()
            conn.commit()
        assert row is not None
        return {
            "id": str(row[0]),
            "tipo": row[1],
            "estado": row[2],
            "created_at": row[3],
        }

    def persona_exists(self, person_id: UUID) -> bool:
        """Return True if any row in `personas` matches the given person_id."""
        with self._pool.connection() as conn:
            row = conn.execute(self._SELECT_PERSONA_EXISTS, (person_id,)).fetchone()
        return row is not None

    def list_admin(
        self,
        *,
        tipo: str | None = None,
        estado: str | None = None,
        limite: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List reports for admin view, optionally filtered by tipo/estado.

        Returns list of ReporteAdmin-shaped dicts (with the publication context
        joined in via a LATERAL subquery: pub_nombre, pub_estado, pub_image_url,
        pub_moderacion). The most recent report comes first.
        """
        conds, args = [], []
        if tipo in self._TIPOS:
            conds.append("r.tipo = %s")
            args.append(tipo)
        if estado in self._ESTADOS:
            conds.append("r.estado = %s")
            args.append(estado)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        args.append(limite)
        args.append(max(0, offset))
        sql = self._LIST_ADMIN.format(where=where)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [self._row_to_admin_dict(r) for r in rows]

    def count_admin(
        self,
        *,
        tipo: str | None = None,
        estado: str | None = None,
    ) -> int:
        """Count reports with the same filters as `list_admin`."""
        conds, args = [], []
        if tipo in self._TIPOS:
            conds.append("r.tipo = %s")
            args.append(tipo)
        if estado in self._ESTADOS:
            conds.append("r.estado = %s")
            args.append(estado)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        sql = self._COUNT_ADMIN.format(where=where)
        with self._pool.connection() as conn:
            row = conn.execute(sql, tuple(args)).fetchone()
        return int(row[0]) if row else 0

    def set_estado(self, reporte_id: UUID, estado: str) -> int:
        """Update `estado` for a single report. Returns rows updated (0 or 1)."""
        with self._pool.connection() as conn:
            n = conn.execute(
                self._UPDATE_ESTADO, (estado, reporte_id)
            ).rowcount
            conn.commit()
        return n

    @staticmethod
    def _row_to_admin_dict(row: tuple) -> dict:
        """Convert one SQL row from the admin-list query into a ReporteAdmin-shaped dict."""
        (
            rid,
            tipo,
            descripcion,
            estado,
            person_id,
            url,
            contacto,
            created_at,
            pub_nombre,
            pub_estado,
            pub_image_url,
            pub_moderacion,
        ) = row
        return {
            "id": str(rid),
            "tipo": tipo,
            "descripcion": descripcion,
            "estado": estado,
            "person_id": str(person_id) if person_id else None,
            "url": url,
            "contacto": contacto,
            "created_at": created_at,
            "pub_nombre": pub_nombre,
            "pub_estado": pub_estado,
            "pub_image_url": pub_image_url,
            "pub_moderacion": pub_moderacion,
        }
