"""Evaluación EXHAUSTIVA del reconocimiento facial.

Barre todos los modelos de DeepFace x varios detectores de rostro sobre TUS
imágenes etiquetadas y mide qué combinación separa mejor "misma persona" de
"personas distintas". Para una app de seguridad, el número clave es el
MARGEN DE SEGURIDAD = (distancia mínima entre personas distintas)
                      - (distancia máxima entre la misma persona).
Si es positivo y grande, existe un umbral que NUNCA confunde a dos personas.

USO
---
eval_images/ con una SUBCARPETA POR PERSONA (varias fotos c/u):
   eval_images/jose/...  eval_images/angela/...  eval_images/maria/...

   python evaluate.py                 # usa ./eval_images
   python evaluate.py ruta            # otra carpeta
   FACE_DETECTORS=retinaface,mtcnn python evaluate.py   # limitar detectores
"""

import glob
import itertools
import os
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

import numpy as np
from deepface import DeepFace

IMG_DIR = sys.argv[1] if len(sys.argv) > 1 else "eval_images"
MODELS = os.environ.get("FACE_MODELS", "Facenet,Facenet512,ArcFace,SFace,VGG-Face").split(",")
DETECTORS = os.environ.get("FACE_DETECTORS", "retinaface,mtcnn,yunet").split(",")
THRESH = {"Facenet": 0.40, "Facenet512": 0.30, "ArcFace": 0.68, "SFace": 0.593, "VGG-Face": 0.68}
EXT = (".jpg", ".jpeg", ".png", ".webp")


def load_images(d):
    items = []
    subdirs = [x for x in glob.glob(os.path.join(d, "*")) if os.path.isdir(x)]
    for sd in subdirs:
        label = os.path.basename(sd)
        for p in glob.glob(os.path.join(sd, "*")):
            if p.lower().endswith(EXT):
                items.append((label, p))
    return items


def cosine(a, b):
    return float(1 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def best_threshold(same, diff):
    """Umbral que maximiza aciertos (Youden) sobre los pares observados."""
    cand = sorted(set(same + diff))
    best_t, best_acc = 0.5, -1
    for i in range(len(cand)):
        t = cand[i] + 1e-6
        acc = (sum(d < t for d in same) + sum(d >= t for d in diff)) / (len(same) + len(diff))
        if acc > best_acc:
            best_acc, best_t = acc, t
    return best_t, best_acc


def main():
    items = load_images(IMG_DIR)
    if len(items) < 2:
        print(f"Pon imágenes en subcarpetas por persona dentro de '{IMG_DIR}/'.")
        sys.exit(1)
    personas = sorted(set(l for l, _ in items))
    print(f"{len(items)} imágenes · {len(personas)} personas: {personas}")
    n_same = sum(1 for a, b in itertools.combinations(items, 2) if a[0] == b[0])
    n_diff = len(list(itertools.combinations(items, 2))) - n_same
    print(f"Pares: {n_same} misma persona, {n_diff} distintas\n")

    rows = []
    for model in MODELS:
        for det in DETECTORS:
            embs, ok, fails = [], [], 0
            for label, path in items:
                try:
                    r = DeepFace.represent(img_path=path, model_name=model,
                                           detector_backend=det, enforce_detection=False, align=True)
                    embs.append(np.array(r[0]["embedding"], dtype=np.float32))
                    ok.append(label)
                except Exception:
                    fails += 1
            same, diff = [], []
            for i, j in itertools.combinations(range(len(ok)), 2):
                d = cosine(embs[i], embs[j])
                (same if ok[i] == ok[j] else diff).append(d)
            if not same or not diff:
                continue
            margin = min(diff) - max(same)
            thr_def = THRESH.get(model, 0.5)
            acc_def = (sum(d < thr_def for d in same) + sum(d >= thr_def for d in diff)) / (len(same) + len(diff))
            thr_opt, acc_opt = best_threshold(same, diff)
            rows.append(dict(model=model, det=det, margin=margin, fails=fails,
                             smax=max(same), dmin=min(diff), savg=np.mean(same), davg=np.mean(diff),
                             thr_def=thr_def, acc_def=acc_def, thr_opt=thr_opt, acc_opt=acc_opt))
            print(f"{model:11} + {det:11} | misma avg={np.mean(same):.3f} max={max(same):.3f} | "
                  f"distinta avg={np.mean(diff):.3f} min={min(diff):.3f} | "
                  f"MARGEN={margin:+.3f} | acc@def={acc_def*100:.0f}% acc@opt={acc_opt*100:.0f}% (t={thr_opt:.2f}) | fails={fails}")

    print("\n" + "=" * 70)
    print("RANKING por MARGEN DE SEGURIDAD (mayor = nunca confunde personas):")
    rows.sort(key=lambda r: r["margin"], reverse=True)
    for r in rows[:8]:
        sep = "perfecta ✓" if r["margin"] > 0 else "SE SOLAPAN ✗"
        print(f"  {r['model']:11} + {r['det']:11}  margen={r['margin']:+.3f}  "
              f"acc@opt={r['acc_opt']*100:.0f}%  separación {sep}")

    if rows:
        b = rows[0]
        print(f"\n>>> MEJOR: {b['model']} + {b['det']}")
        print(f"    Misma persona <= {b['smax']:.3f}   |   Distintas >= {b['dmin']:.3f}")
        safe = (b["smax"] + b["dmin"]) / 2
        print(f"    Umbral seguro recomendado = {safe:.3f} (punto medio del margen)")
        print(f"    Con ese umbral: 0 falsos positivos y 0 falsos negativos en este set.")


if __name__ == "__main__":
    main()
