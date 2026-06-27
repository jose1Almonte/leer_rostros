from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración del servicio, cargada desde variables de entorno / .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # DigitalOcean Spaces (compatible con S3)
    spaces_key: str
    spaces_secret: str
    spaces_region: str = "nyc3"
    spaces_bucket: str
    spaces_endpoint: str | None = None
    spaces_cdn_endpoint: str | None = None

    # DigitalOcean Managed Postgres (con pgvector)
    database_url: str

    # Reconocimiento facial — InsightFace buffalo_l (ArcFace w600k_r50, 512-dim).
    # buffalo_l es SOTA en benchmarks cross-pose (CFP-FP), entrenado con augmentación
    # masiva de ángulo. Umbral y curva sigmoide a calibrar con evaluate.py.
    embedding_dim: int = 512
    match_threshold: float = 0.55
    min_face_quality: float = 0.50          # det_score mínimo de insightface (0–1)
    confidence_sigmoid_k: float = 12.0      # pendiente de la curva sigmoide
    confidence_sigmoid_midpoint: float = 0.40  # distancia donde confianza = 50 %

    @property
    def endpoint_url(self) -> str:
        """Endpoint S3 del Space; se deriva de la región si no se define."""
        return self.spaces_endpoint or f"https://{self.spaces_region}.digitaloceanspaces.com"

    @property
    def public_base_url(self) -> str:
        """Base pública para construir la URL de cada imagen subida."""
        if self.spaces_cdn_endpoint:
            return self.spaces_cdn_endpoint.rstrip("/")
        return f"https://{self.spaces_bucket}.{self.spaces_region}.digitaloceanspaces.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
