"""MatchRepository: SQL del add-on sobre `coincidencias` + lectura de personas/embeddings.

Reusa las tablas `personas` y `persona_embeddings` que ya pueblan los flujos de app.
El barrido es bidireccional por diseño: tomamos cada BUSCADA y buscamos su mejor
ENCONTRADA por distancia coseno (pgvector), sin depender de la moderación (el cron
detecta aunque la encontrada esté 'pendiente' de aprobar)."""

from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool

from app.domain.matching import MatchingPolicy


class MatchRepository:
    # Un embedding representativo por persona BUSCADA (el más antiguo = foto base).
    _BUSCADAS = """
        SELECT DISTINCT ON (p.person_id)
               p.person_id, p.nombre, p.apellido, p.telefono_contacto, pe.embedding
        FROM personas p
        JOIN persona_embeddings pe ON pe.foto_id = p.id
        WHERE p.estado = 'buscada'
        ORDER BY p.person_id, pe.created_at ASC
        {limit}
    """

    # Mejor ENCONTRADA para un embedding dado (mejor distancia entre sus embeddings).
    _MEJOR_ENCONTRADA = """
        SELECT p2.person_id, p2.es_menor, p2.nombre, p2.apellido,
               p2.refugio, p2.ubicacion, p2.encontrado_por,
               coalesce(p2.telefono_responsable, p2.telefono_contacto) AS telefono,
               p2.image_url, b.distancia
        FROM (
            SELECT p.person_id, min(pe.embedding <=> %s) AS distancia
            FROM persona_embeddings pe
            JOIN personas p ON p.id = pe.foto_id
            WHERE p.estado = 'encontrada'
            GROUP BY p.person_id
            ORDER BY distancia ASC
            LIMIT 1
        ) b
        JOIN personas p2 ON p2.person_id = b.person_id
        ORDER BY p2.created_at ASC
        LIMIT 1
    """

    # Inserta el match; ON CONFLICT no duplica. RETURNING devuelve fila solo si es nuevo.
    _INSERT_MATCH = """
        INSERT INTO coincidencias
            (buscada_person_id, encontrada_person_id, distancia, coincidencia,
             confianza, estado_notificacion)
        VALUES (%(buscada)s, %(encontrada)s, %(distancia)s, %(coincidencia)s,
                %(confianza)s, %(estado)s)
        ON CONFLICT (buscada_person_id, encontrada_person_id) DO NOTHING
        RETURNING id
    """

    # Matches por avisar, con los datos para armar el mensaje. Incluye reintentos:
    #   - 'pendiente'    -> nuevo, por enviar
    #   - 'sin_telefono' -> se re-evalúa por si el familiar ya dejó teléfono
    #   - 'fallida'      -> falla transitoria, reintenta mientras intentos < tope
    _PENDIENTES = """
        SELECT c.id, c.coincidencia, c.confianza,
               fb.nombre, fb.apellido, fb.telefono_contacto,
               fe.nombre, fe.refugio, fe.ubicacion, fe.encontrado_por,
               coalesce(fe.telefono_responsable, fe.telefono_contacto)
        FROM coincidencias c
        JOIN LATERAL (
            SELECT nombre, apellido, telefono_contacto FROM personas
            WHERE person_id = c.buscada_person_id ORDER BY created_at LIMIT 1
        ) fb ON true
        JOIN LATERAL (
            SELECT nombre, refugio, ubicacion, encontrado_por,
                   telefono_responsable, telefono_contacto FROM personas
            WHERE person_id = c.encontrada_person_id ORDER BY created_at LIMIT 1
        ) fe ON true
        WHERE c.estado_notificacion IN ('pendiente', 'sin_telefono')
           OR (c.estado_notificacion = 'fallida' AND c.intentos < %s)
        ORDER BY c.created_at ASC
    """

    _MARCAR = """
        UPDATE coincidencias
        SET estado_notificacion = %(estado)s, wa_to = %(wa_to)s, canal = %(canal)s,
            wa_message_id = %(msg_id)s, error = %(error)s,
            intentos = intentos + %(inc)s,
            notified_at = CASE WHEN %(estado)s = 'enviada' THEN now() ELSE notified_at END
        WHERE id = %(id)s
    """

    # Un admin contactó manualmente a la familia → el cron no debe reenviar.
    _MARCAR_CONTACTADO = """
        UPDATE coincidencias SET estado_notificacion = 'contactado'
        WHERE buscada_person_id = %s
          AND estado_notificacion IN ('pendiente', 'sin_telefono', 'fallida')
    """

    _LISTAR = """
        SELECT id, buscada_person_id, encontrada_person_id, distancia, coincidencia,
               confianza, estado_notificacion, wa_to, error, created_at, notified_at
        FROM coincidencias
        {where}
        ORDER BY created_at DESC
        LIMIT %s
    """

    def __init__(self, pool: ConnectionPool, policy: MatchingPolicy):
        self._pool = pool
        self._policy = policy

    @property
    def policy(self) -> MatchingPolicy:
        return self._policy

    # ----------------------------- lectura -----------------------------

    def buscadas_con_embedding(self, limite: int = 0) -> list[dict]:
        sql = self._BUSCADAS.format(limit="LIMIT %s" if limite else "")
        with self._pool.connection() as conn:
            rows = conn.execute(sql, (limite,) if limite else ()).fetchall()
        return [
            {
                "person_id": r[0],
                "nombre": r[1],
                "apellido": r[2],
                "telefono_contacto": r[3],
                "embedding": r[4],
            }
            for r in rows
        ]

    def mejor_encontrada(self, embedding: Any) -> dict | None:
        with self._pool.connection() as conn:
            row = conn.execute(self._MEJOR_ENCONTRADA, (embedding,)).fetchone()
        if not row:
            return None
        d = float(row[9])
        return {
            "person_id": row[0],
            "es_menor": bool(row[1]),
            "nombre": row[2],
            "apellido": row[3],
            "refugio": row[4],
            "ubicacion": row[5],
            "encontrado_por": row[6],
            "telefono": row[7],
            "image_url": row[8],
            "distancia": round(d, 4),
            "coincidencia": self._policy.match_percentage(d),
            "confianza": self._policy.confidence_band(d),
        }

    def pendientes_de_notificar(self, max_intentos: int = 5) -> list[dict]:
        with self._pool.connection() as conn:
            rows = conn.execute(self._PENDIENTES, (max_intentos,)).fetchall()
        return [
            {
                "id": r[0],
                "coincidencia": r[1],
                "confianza": r[2],
                "buscada_nombre": r[3],
                "buscada_apellido": r[4],
                "familiar_telefono": r[5],
                "encontrada_nombre": r[6],
                "refugio": r[7],
                "ubicacion": r[8],
                "encontrado_por": r[9],
                "telefono_responsable": r[10],
            }
            for r in rows
        ]

    def telefono_familiar(self, buscada_person_id: str | UUID) -> dict | None:
        """Datos del familiar (para el botón Contactar) por person_id de la buscada."""
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT nombre, apellido, telefono_contacto FROM personas "
                "WHERE person_id = %s ORDER BY created_at LIMIT 1",
                (buscada_person_id,),
            ).fetchone()
        if not row:
            return None
        return {"nombre": row[0], "apellido": row[1], "telefono": row[2]}

    def listar(self, limite: int = 100, estado: str | None = None) -> list[dict]:
        where, args = "", []
        if estado:
            where = "WHERE estado_notificacion = %s"
            args.append(estado)
        args.append(limite)
        sql = self._LISTAR.format(where=where)
        with self._pool.connection() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [
            {
                "id": str(r[0]),
                "buscada_person_id": str(r[1]),
                "encontrada_person_id": str(r[2]),
                "distancia": round(float(r[3]), 4),
                "coincidencia": r[4],
                "confianza": r[5],
                "estado_notificacion": r[6],
                "wa_to": r[7],
                "error": r[8],
                "created_at": r[9],
                "notified_at": r[10],
            }
            for r in rows
        ]

    # ----------------------------- escritura -----------------------------

    def registrar_match(
        self,
        *,
        buscada_person_id: str | UUID,
        encontrada_person_id: str | UUID,
        distancia: float,
        coincidencia: int,
        confianza: str,
        sin_telefono: bool,
    ) -> str | None:
        """Inserta un match nuevo. Devuelve su id, o None si ya existía (ON CONFLICT)."""
        estado = "sin_telefono" if sin_telefono else "pendiente"
        with self._pool.connection() as conn:
            row = conn.execute(
                self._INSERT_MATCH,
                {
                    "buscada": str(buscada_person_id),
                    "encontrada": str(encontrada_person_id),
                    "distancia": distancia,
                    "coincidencia": coincidencia,
                    "confianza": confianza,
                    "estado": estado,
                },
            ).fetchone()
            conn.commit()
        return str(row[0]) if row else None

    def marcar(
        self,
        match_id: str,
        *,
        estado: str,
        wa_to: str | None = None,
        msg_id: str | None = None,
        error: str | None = None,
        canal: str = "whatsapp",
        inc_intentos: int = 0,
    ) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                self._MARCAR,
                {
                    "id": match_id,
                    "estado": estado,
                    "wa_to": wa_to,
                    "msg_id": msg_id,
                    "error": error,
                    "canal": canal,
                    "inc": inc_intentos,
                },
            )
            conn.commit()

    def marcar_contactado(self, buscada_person_id: str | UUID) -> int:
        """Marca como 'contactado' los matches pendientes de esa buscada (contacto
        manual del admin) para que el cron no reenvíe. Devuelve filas afectadas."""
        with self._pool.connection() as conn:
            n = conn.execute(self._MARCAR_CONTACTADO, (str(buscada_person_id),)).rowcount
            conn.commit()
        return n
