"""Calcula embeddings faciales LOCALMENTE para el lote de personas encontradas.

Pensado para correr DENTRO del contenedor Docker (que ya tiene InsightFace), usando los
12 cores locales en vez de los 2 del servidor. NO toca la base de datos: produce dos cosas
que luego se transfieren al servidor:

  1. <out>/records.jsonl  -> una línea por persona con sus datos + foto_id + embedding(512).
  2. <out>/staging/personas/<foto_id>.jpg  -> la imagen, renombrada al foto_id.

Decisiones de este lote (confirmadas con el usuario):
  - Sin moderación (dataset confiable de personas ya encontradas).
  - es_menor = edad < 18 (aplica privacidad de menores).
  - Solo embedding base (sin augmentación) — rápido y suficiente para el set de referencia.
  - Idempotente/reanudable: salta los `codigo` que ya estén en records.jsonl.
  - Salta imágenes vacías/corruptas o sin rostro detectable (las loguea en skipped.log).

Uso (en Docker):
  python scripts/embeddings_local.py \
      --json final/final/valid_personas.json \
      --images final/final/images \
      --out /out --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from concurrent.futures import ProcessPoolExecutor

# --- worker (un modelo InsightFace por proceso) ---------------------------- #

_app = None


def _init_worker():
    global _app
    import app.faces as faces

    _app = faces


def _embed_path(path: str):
    """Devuelve (embedding_list, score) o None si no hay rostro / error."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if not data:
            return None
        emb, score = _app.embedding_from_bytes(data)
        return (emb.tolist(), float(score))
    except Exception:
        return None


# --- main ------------------------------------------------------------------ #


def _s(v) -> str | None:
    """Convierte cualquier valor del JSON a string limpio o None (tolera int/float)."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _es_menor(edad) -> bool:
    e = _s(edad)
    return bool(e) and e.isdigit() and int(e) < 18


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="Solo procesar N (0=todos).")
    args = ap.parse_args()

    staging = os.path.join(args.out, "staging", "personas")
    os.makedirs(staging, exist_ok=True)
    records_path = os.path.join(args.out, "records.jsonl")
    skipped_path = os.path.join(args.out, "skipped.log")

    with open(args.json, encoding="utf-8") as f:
        registros = json.load(f)

    # Reanudación: codigos ya procesados.
    hechos: set[str] = set()
    if os.path.exists(records_path):
        with open(records_path, encoding="utf-8") as f:
            for line in f:
                try:
                    hechos.add(json.loads(line)["codigo"])
                except Exception:
                    pass
    print(f"[ingest] total={len(registros)} ya_hechos={len(hechos)}", flush=True)

    # Construir lista de trabajo (registro, path) para imágenes existentes y no hechas.
    trabajo = []
    saltados_archivo = 0
    for r in registros:
        cod = r.get("id")
        if not cod or cod in hechos:
            continue
        path = os.path.join(args.images, f"{cod}.jpg")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            saltados_archivo += 1
            continue
        trabajo.append((r, path))
    if args.limit:
        trabajo = trabajo[: args.limit]
    print(f"[ingest] a_procesar={len(trabajo)} sin_imagen={saltados_archivo}", flush=True)

    # Pre-cargar el modelo una vez (descarga buffalo_l si hace falta) ANTES del pool,
    # así los workers leen el caché y no hay carrera de descarga.
    import app.faces as faces

    faces.warmup()

    ok = sin_rostro = 0
    with (
        open(records_path, "a", encoding="utf-8") as out_f,
        open(skipped_path, "a", encoding="utf-8") as skip_f,
        ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker) as ex,
    ):
        paths = [p for _, p in trabajo]
        for (r, path), res in zip(trabajo, ex.map(_embed_path, paths, chunksize=8)):
            cod = r["id"]
            if res is None:
                sin_rostro += 1
                skip_f.write(f"{cod}\tsin_rostro_o_error\n")
                continue
            emb, score = res
            foto_id = str(uuid.uuid4())
            shutil.copyfile(path, os.path.join(staging, f"{foto_id}.jpg"))
            rec = {
                "codigo": cod,
                "foto_id": foto_id,
                "nombre": _s(r.get("nombre_pila")) or _s(r.get("nombre")),
                "apellido": _s(r.get("apellido")),
                "edad": _s(r.get("edad")),
                "cedula": _s(r.get("cedula")),
                "ubicacion": _s(r.get("ultima_ubicacion")),
                "telefono": _s(r.get("reportante_phone")),
                "fuente": _s(r.get("fuente")),
                "es_menor": _es_menor(r.get("edad")),
                "calidad": round(score, 4),
                "embedding": emb,
            }
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            ok += 1
            if ok % 500 == 0:
                print(f"[ingest] ok={ok} sin_rostro={sin_rostro}", flush=True)

    print(f"[ingest] LISTO ok={ok} sin_rostro={sin_rostro} sin_imagen={saltados_archivo}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
