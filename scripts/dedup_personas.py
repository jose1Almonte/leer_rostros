"""Detecta (y opcionalmente elimina) personas DUPLICADAS por imagen idéntica.

Señal usada: el **md5 del archivo de la foto**. Si dos personas distintas tienen el
MISMO archivo de imagen, casi seguro son la misma persona scrapeada dos veces. Se
conserva la MÁS ANTIGUA (min created_at) de cada grupo y se marcan las demás.

SEGURO POR DEFECTO: corre en **dry-run** (solo reporta, NO borra). Para borrar de verdad
hay que pasar `--apply` explícitamente.

Guardas:
- `--max-grupo N` (def 5): los grupos con MÁS de N copias se SALTAN (probable imagen
  placeholder/genérica, no duplicado real) y se listan para revisión manual.
- Solo considera personas con la MISMA imagen; no toca nada por nombre/cédula.

Uso (en el servidor, en /mnt/volumen1/rostros con el venv):
  ./venv/bin/python scripts/dedup_personas.py                # dry-run (no borra)
  ./venv/bin/python scripts/dedup_personas.py --apply        # BORRA de verdad
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import defaultdict

import psycopg

from app.config import get_settings


def _md5(path: str) -> str | None:
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="BORRA de verdad (sin esto, dry-run).")
    ap.add_argument("--max-grupo", type=int, default=5,
                    help="Saltar grupos con más de N copias (placeholder). Def 5.")
    args = ap.parse_args()

    s = get_settings()
    storage_dir = s.local_storage_dir

    # Una fila por persona (su foto más antigua representa al person_id).
    with psycopg.connect(s.database_url) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT ON (person_id) person_id, image_key, created_at
            FROM personas
            ORDER BY person_id, created_at ASC
            """
        ).fetchall()

    print(f"[dedup] personas únicas: {len(rows)}  (storage={storage_dir})", flush=True)

    # Agrupar person_id por md5 de su imagen.
    por_md5: dict[str, list] = defaultdict(list)
    sin_archivo = 0
    for person_id, image_key, created_at in rows:
        path = os.path.join(storage_dir, image_key)
        digest = _md5(path)
        if digest is None:
            sin_archivo += 1
            continue
        por_md5[digest].append((created_at, str(person_id)))

    a_borrar: list[str] = []
    grupos_dup = grupos_placeholder = 0
    for digest, miembros in por_md5.items():
        if len(miembros) < 2:
            continue
        if len(miembros) > args.max_grupo:
            grupos_placeholder += 1
            print(f"[dedup] SALTO grupo placeholder ({len(miembros)} copias) md5={digest[:10]}", flush=True)
            continue
        grupos_dup += 1
        # conservar la más antigua; borrar el resto
        miembros.sort(key=lambda m: m[0])
        a_borrar.extend(pid for _, pid in miembros[1:])

    print(f"[dedup] grupos duplicados: {grupos_dup}  | placeholders saltados: {grupos_placeholder}", flush=True)
    print(f"[dedup] personas a eliminar: {len(a_borrar)}  | sin_archivo: {sin_archivo}", flush=True)

    if not args.apply:
        print("[dedup] DRY-RUN (no se borró nada). Pasá --apply para ejecutar.", flush=True)
        # dejar el listado para auditoría
        with open("dedup_a_borrar.txt", "w") as f:
            f.write("\n".join(a_borrar))
        print("[dedup] listado escrito en dedup_a_borrar.txt", flush=True)
        return 0

    # --apply: borrar personas (CASCADE borra embeddings) + archivos.
    borrados = 0
    with psycopg.connect(s.database_url) as conn:
        for pid in a_borrar:
            keys = [
                r[0]
                for r in conn.execute(
                    "SELECT image_key FROM personas WHERE person_id = %s", (pid,)
                ).fetchall()
            ]
            conn.execute("DELETE FROM personas WHERE person_id = %s", (pid,))
            conn.commit()
            for k in keys:
                try:
                    os.remove(os.path.join(storage_dir, k))
                except FileNotFoundError:
                    pass
            borrados += 1
            if borrados % 500 == 0:
                print(f"[dedup] borrados={borrados}", flush=True)
    print(f"[dedup] LISTO. personas borradas: {borrados}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
