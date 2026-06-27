"""CLI para gestión de admins.

Uso:
    python -m app.cli create-admin --user <username>
    python -m app.cli change-password <username>
    python -m app.cli deactivate-admin <username>
    python -m app.cli activate-admin <username>
    python -m app.cli list-admins

Las passwords se leen de stdin (ocultas) si no se pasan con --password.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.auth import (
    get_admin_by_username,
    hash_password,
    verify_password,
)
from app.database import get_pool


def _prompt_password(confirm: bool = True) -> str:
    """Pide password por stdin (oculta). Si `confirm`, la pide dos veces."""
    pw1 = getpass.getpass("Password: ")
    if not pw1:
        print("La password no puede estar vacía.", file=sys.stderr)
        sys.exit(2)
    if confirm:
        pw2 = getpass.getpass("Confirmar:  ")
        if pw1 != pw2:
            print("Las passwords no coinciden.", file=sys.stderr)
            sys.exit(2)
    return pw1


def _ensure_user(username: str):
    """Helper: devuelve el admin por username o aborta con error claro."""
    with get_pool().connection() as conn:
        admin = get_admin_by_username(conn, username)
    if admin is None:
        print(f"ERROR: no existe el admin '{username}'.", file=sys.stderr)
        sys.exit(1)
    return admin


# --------------------------------------------------------------------------- #
# Subcomandos
# --------------------------------------------------------------------------- #


def cmd_create_admin(args: argparse.Namespace) -> None:
    username = args.user
    password = args.password or _prompt_password(confirm=True)

    with get_pool().connection() as conn:
        if get_admin_by_username(conn, username) is not None:
            print(f"ERROR: ya existe el admin '{username}'.", file=sys.stderr)
            sys.exit(1)
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
            (username, hash_password(password)),
        )
        conn.commit()
    print(f"Admin '{username}' creado.")


def cmd_change_password(args: argparse.Namespace) -> None:
    username = args.username
    new_password = args.password or _prompt_password(confirm=True)

    # Si la nueva password vino por stdin (sin --password), verificamos la actual
    # para que un atacante con acceso al shell no pueda cambiarla ciegamente.
    if not args.password:
        current = getpass.getpass("Password actual: ")
        with get_pool().connection() as conn:
            admin = get_admin_by_username(conn, username)
            if admin is None or not verify_password(
                current, _password_hash(conn, admin.id)
            ):
                print("Password actual incorrecta.", file=sys.stderr)
                sys.exit(1)

    with get_pool().connection() as conn:
        n = conn.execute(
            "UPDATE admins SET password_hash = %s WHERE username = %s",
            (hash_password(new_password), username),
        ).rowcount
        conn.commit()
    if not n:
        print(f"ERROR: no existe el admin '{username}'.", file=sys.stderr)
        sys.exit(1)
    print(f"Password de '{username}' actualizada.")


def _password_hash(conn, admin_id) -> str:
    """Carga el hash actual (usado por change-password para verificar la actual)."""
    row = conn.execute(
        "SELECT password_hash FROM admins WHERE id = %s", (admin_id,)
    ).fetchone()
    return row[0] if row else ""


def cmd_set_active(args: argparse.Namespace) -> None:
    username = args.username
    admin = _ensure_user(username)
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE admins SET is_active = %s WHERE id = %s",
            (args.active, admin.id),
        )
        conn.commit()
    state = "activado" if args.active else "desactivado"
    print(f"Admin '{username}' {state}.")


def cmd_list_admins(_: argparse.Namespace) -> None:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT username, is_active, created_at, last_login_at "
            "FROM admins ORDER BY created_at"
        ).fetchall()
    if not rows:
        print("(sin admins)")
        return
    print(f"{'USERNAME':<20} {'ACTIVO':<7} {'CREADO':<20} ÚLTIMO LOGIN")
    for username, active, created, last_login in rows:
        print(
            f"{username:<20} "
            f"{'sí' if active else 'no':<7} "
            f"{created.isoformat() if created else '-':<20} "
            f"{last_login.isoformat() if last_login else '-'}"
        )


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Gestión de admins del servicio de reencuentros.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("create-admin", help="Crear un nuevo admin.")
    s.add_argument("--user", required=True, help="Username único.")
    s.add_argument("--password", help="Password (si se omite, se pide por stdin).")
    s.set_defaults(func=cmd_create_admin)

    s = sub.add_parser("change-password", help="Cambiar la password de un admin.")
    s.add_argument("username", help="Username del admin.")
    s.add_argument(
        "--password", help="Nueva password (si se omite, se pide por stdin)."
    )
    s.set_defaults(func=cmd_change_password)

    s = sub.add_parser(
        "deactivate-admin", help="Desactivar un admin (no puede loguearse)."
    )
    s.add_argument("username")
    s.set_defaults(func=cmd_set_active, active=False)

    s = sub.add_parser("activate-admin", help="Reactivar un admin desactivado.")
    s.add_argument("username")
    s.set_defaults(func=cmd_set_active, active=True)

    s = sub.add_parser("list-admins", help="Listar admins existentes.")
    s.set_defaults(func=cmd_list_admins)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
