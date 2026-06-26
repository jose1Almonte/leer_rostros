"""Extracción del embedding facial con DeepFace (modelo Facenet por defecto)."""

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

import cv2
import numpy as np
from deepface import DeepFace

from app.config import get_settings


def embedding_from_bytes(data: bytes) -> np.ndarray:
    """Decodifica los bytes de una imagen y devuelve su vector facial (float32)."""
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo decodificar la imagen (formato no soportado o archivo corrupto)")

    # Reescalar imágenes grandes antes de detectar: retinaface es CPU-pesado y las
    # fotos de móvil vienen en ~3000x4000. Bajar a ~1000px acelera mucho la detección
    # sin perder precisión (el rostro sigue bien definido).
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest > 1000:
        scale = 1000.0 / longest
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    s = get_settings()
    resultado = DeepFace.represent(
        img_path=img,
        model_name=s.face_model,
        detector_backend=s.face_detector,  # retinaface alinea mejor el rostro
        enforce_detection=False,
        align=True,
    )
    return np.asarray(resultado[0]["embedding"], dtype=np.float32)


def warmup() -> None:
    """Pre-carga el modelo y el detector para evitar el cold start en la 1ª petición."""
    s = get_settings()
    dummy = np.zeros((320, 320, 3), dtype=np.uint8)
    try:
        DeepFace.represent(
            img_path=dummy, model_name=s.face_model,
            detector_backend=s.face_detector, enforce_detection=False, align=True,
        )
    except Exception:
        pass
