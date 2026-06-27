"""Auth de admin: hash de password, JWT firmado, y guard FastAPI.

Diseño:
  - Los passwords NUNCA se guardan en plano: bcrypt (passlib).
  - El login (main.admin_login) valida contra la tabla `admins` con verify_password.
  - El token es un JWT firmado (HS256) con `sub` = admin_id y `exp` automático.
  - `get_current_admin` es la dependency de FastAPI que se usa en endpoints admin:
        @app.get(..., dependencies=[Depends(get_current_admin)])
    Valida el header `Authorization: Bearer <token>`, decodifica el JWT y carga
    la fila del admin (chequeando `is_active`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Header, HTTPException
from passlib.context import CryptContext

from app.config import get_settings

# Algoritmo de hashing de passwords. `deprecated="auto"` para que passlib
# migre automáticamente si actualizamos el scheme.
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #


def hash_password(plain: str) -> str:
    """Hashea una password en plano con bcrypt. Devuelve el hash para guardar en BD."""
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Compara una password en plano contra un hash bcrypt. Constante en tiempo."""
    try:
        return _pwd.verify(plain, hashed)
    except (ValueError, TypeError):
        # Hash malformado o esquema desconocido: no es un match.
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #


def _require_jwt_secret() -> str:
    """Falla rápido si JWT_SECRET no está configurado (no usamos un default conocido)."""
    secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError(
            "Falta JWT_SECRET en el entorno. Generá uno con "
            '`python -c "import secrets; print(secrets.token_urlsafe(64))"` '
            "y setéalo en .env"
        )
    return secret


def create_access_token(admin_id: uuid.UUID, username: str) -> str:
    """Firma un JWT con `sub`=admin_id, `username` y `exp` automático."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(admin_id),
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.jwt_expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, _require_jwt_secret(), algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodifica y valida un JWT. Lanza `HTTPException(401)` si está expirado o mal firmado."""
    s = get_settings()
    try:
        return jwt.decode(token, _require_jwt_secret(), algorithms=[s.jwt_algorithm])
    except jwt.ExpiredSignatureError as err:
        raise HTTPException(401, "Token expirado. Iniciá sesión de nuevo.") from err
    except jwt.InvalidTokenError as err:
        raise HTTPException(401, "Token inválido.") from err


# --------------------------------------------------------------------------- #
# Capa de datos: admins
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Admin:
    """Representación inmutable de un admin (la fila de la BD)."""

    id: uuid.UUID
    username: str
    is_active: bool

    @classmethod
    def from_row(cls, row: tuple) -> Admin:
        # El SELECT debe traer columnas en este orden: id, username, is_active.
        return cls(id=row[0], username=row[1], is_active=row[2])


def _fetch_admin_by(cur, column: str, value: Any) -> Admin | None:
    """Helper interno. `column` debe ser un nombre de columna validado externamente."""
    row = cur.execute(
        f"SELECT id, username, is_active FROM admins WHERE {column} = %s",
        (value,),
    ).fetchone()
    return Admin.from_row(row) if row else None


def get_admin_by_username(conn, username: str) -> Admin | None:
    return _fetch_admin_by(conn, "username", username)


def get_admin_by_id(conn, admin_id: uuid.UUID) -> Admin | None:
    return _fetch_admin_by(conn, "id", admin_id)


def touch_last_login(conn, admin_id: uuid.UUID) -> None:
    """Actualiza `last_login_at = now()` tras un login exitoso. No falla si la fila no existe."""
    conn.execute("UPDATE admins SET last_login_at = now() WHERE id = %s", (admin_id,))


# --------------------------------------------------------------------------- #
# Guard de FastAPI
# --------------------------------------------------------------------------- #


def get_current_admin(
    authorization: str | None = Header(None, description="Bearer <token>."),
) -> Admin:
    """Dependency de FastAPI: protege endpoints de admin.

    Uso:
        @app.get("/admin/...", dependencies=[Depends(get_current_admin)])

    Flujo:
      1. Lee `Authorization: Bearer <token>`.
      2. Decodifica el JWT (firma + expiración).
      3. Carga la fila del admin por `sub` (= admin_id).
      4. Verifica que esté `is_active`.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "No autorizado. Iniciá sesión en POST /admin/login.")
    token = authorization[len("Bearer ") :].strip()
    if not token:
        raise HTTPException(401, "No autorizado. Token vacío.")

    payload = decode_access_token(token)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "Token inválido.")

    try:
        admin_id = uuid.UUID(sub)
    except (ValueError, TypeError) as err:
        raise HTTPException(401, "Token inválido.") from err

    # Import local para evitar import circular: database importa config, no auth.
    from app.database import get_pool

    with get_pool().connection() as conn:
        admin = get_admin_by_id(conn, admin_id)

    if admin is None:
        raise HTTPException(401, "No autorizado. El admin ya no existe.")
    if not admin.is_active:
        raise HTTPException(403, "Cuenta desactivada.")
    return admin
