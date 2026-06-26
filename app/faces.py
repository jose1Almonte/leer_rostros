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

    s = get_settings()
    resultado = DeepFace.represent(
        img_path=img,
        model_name=s.face_model,
        enforce_detection=False,
    )
    return np.asarray(resultado[0]["embedding"], dtype=np.float32)
