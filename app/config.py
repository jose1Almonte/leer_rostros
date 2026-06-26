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

    # Reconocimiento facial
    face_model: str = "Facenet"
    embedding_dim: int = 128
    match_threshold: float = 0.40

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
