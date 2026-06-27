from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración del servicio, cargada desde variables de entorno / .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Almacenamiento de imágenes.
    # Por defecto: LOCAL (carpeta del contenedor) -> cero configuración.
    # Si defines SPACES_KEY/SECRET/BUCKET, usa DigitalOcean Spaces (S3).
    spaces_key: str = ""
    spaces_secret: str = ""
    spaces_region: str = "nyc3"
    spaces_bucket: str = ""
    spaces_endpoint: str | None = None
    spaces_cdn_endpoint: str | None = None
    local_storage_dir: str = "/data/fotos"

    # Base de datos. Por defecto apunta al Postgres incluido en la imagen.
    database_url: str = "postgresql://rostros:rostros@localhost:5432/rostros"

    @property
    def usa_spaces(self) -> bool:
        return bool(self.spaces_key and self.spaces_secret and self.spaces_bucket)

    # Reconocimiento facial.
    # Facenet512 + retinaface = mejor combinación según benchmark a escala (LFW
    # 97-100%) y la literatura: el más robusto a fotos mal encuadradas y diversas,
    # ideal para fotos de rescate. SFace gana en fotos perfectas pero NO generaliza.
    # Umbral 0.50 calibrado con datos reales (misma persona <=0.469, distintas >=0.549).
    face_model: str = "Facenet512"
    embedding_dim: int = 512
    match_threshold: float = 0.50
    face_detector: str = "retinaface"

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
