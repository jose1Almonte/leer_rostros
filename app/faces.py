"""Extracción de embeddings faciales con InsightFace (buffalo_l).

buffalo_l usa ArcFace w600k_r50 (512-dim) como reconocedor y RetinaFace como detector,
entrenado con augmentación masiva de pose — mucho más robusto a ángulos que SFace.
"""

import math

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from app.config import get_settings

_face_app: FaceAnalysis | None = None


def _get_app() -> FaceAnalysis:
    global _face_app
    if _face_app is None:
        _face_app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        # det_size=(640,640): balance entre precisión de detección y velocidad CPU.
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
    return _face_app


def _decode_and_resize(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo decodificar la imagen (formato no soportado o archivo corrupto)")
    # Reescalar fotos grandes: fotos de móvil ~3000x4000 son innecesariamente pesadas.
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest > 1000:
        scale = 1000.0 / longest
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _best_face(img: np.ndarray, min_quality: float) -> tuple[np.ndarray, float]:
    """Detecta el mejor rostro en la imagen BGR y devuelve (embedding_512dim, det_score)."""
    app = _get_app()
    detected = app.get(img)
    if not detected:
        raise ValueError("No se detectó ningún rostro en la imagen.")
    face = max(detected, key=lambda f: f.det_score)
    if face.det_score < min_quality:
        raise ValueError(
            f"Calidad del rostro insuficiente ({face.det_score:.2f}). "
            "Suba una foto más clara, de frente o con mejor iluminación."
        )
    # normed_embedding ya está L2-normalizado → distancia coseno = 1 - dot product.
    return np.asarray(face.normed_embedding, dtype=np.float32), float(face.det_score)


def embedding_from_bytes(data: bytes) -> tuple[np.ndarray, float]:
    """Decodifica la imagen y devuelve (embedding 512-dim, calidad_detección)."""
    s = get_settings()
    img = _decode_and_resize(data)
    return _best_face(img, s.min_face_quality)


def embeddings_from_bytes(data: bytes) -> list[tuple[np.ndarray, float]]:
    """Extrae el embedding base + augmentaciones por rotación (±15°) de una sola foto.

    Al registrar, esto genera hasta 3 vectores de una sola foto: uno frontal y dos
    con leve rotación. Cubre variaciones de ángulo sin pedir fotos extra al usuario.
    Solo se incluyen las augmentaciones donde el detector localiza un rostro.
    """
    s = get_settings()
    img = _decode_and_resize(data)
    results: list[tuple[np.ndarray, float]] = []

    # Embedding base — si falla (sin rostro o calidad baja), propagamos el error.
    base_emb, base_qual = _best_face(img, s.min_face_quality)
    results.append((base_emb, base_qual))

    # Augmentaciones: rotaciones suaves para mayor cobertura de ángulo.
    h, w = img.shape[:2]
    center = (w / 2.0, h / 2.0)
    for angle in (-15.0, 15.0):
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(img, M, (w, h))
        try:
            emb, qual = _best_face(rotated, s.min_face_quality)
            results.append((emb, qual))
        except ValueError:
            pass  # Augmentación no útil — se omite silenciosamente.

    return results


def distance_to_confidence(distance: float) -> float:
    """Convierte distancia coseno → porcentaje de confianza (0–100%) con sigmoide calibrada.

    La sigmoide está centrada en `confidence_sigmoid_midpoint` (distancia de incertidumbre)
    con pendiente `confidence_sigmoid_k`. Valores típicos con buffalo_l:
      - distancia 0.10 → ~97 %  (match muy claro)
      - distancia 0.25 → ~85 %  (match sólido)
      - distancia 0.40 → ~50 %  (punto de incertidumbre)
      - distancia 0.55 → ~16 %  (en el umbral — revisar manualmente)
    """
    s = get_settings()
    raw = 1.0 / (1.0 + math.exp(s.confidence_sigmoid_k * (distance - s.confidence_sigmoid_midpoint)))
    return round(raw * 100.0, 1)


def warmup() -> None:
    """Pre-carga el modelo y el detector para evitar el cold start en la primera petición."""
    dummy = np.zeros((320, 320, 3), dtype=np.uint8)
    try:
        _get_app().get(dummy)
    except Exception:
        pass
