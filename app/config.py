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

    # CORS: orígenes (front) autorizados a consumir la API desde el navegador.
    # Lista separada por comas. RESTRINGIDO a los fronts de producción (con y sin www)
    # más el panel de admin. Para abrir a todos en desarrollo: CORS_ORIGINS="*".
    # Para agregar un entorno local: CORS_ORIGINS="https://vzlaencuentra.com,http://localhost:5173"
    cors_origins: str = (
        "https://vzlaencuentra.com,https://www.vzlaencuentra.com,"
        "https://admin-personas-private.netlify.app"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """`cors_origins` como lista, sin espacios ni entradas vacías."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def usa_spaces(self) -> bool:
        return bool(self.spaces_key and self.spaces_secret and self.spaces_bucket)

    # Reconocimiento facial — InsightFace buffalo_l (ArcFace w600k_r50, 512-dim) +
    # RetinaFace como detector. buffalo_l es SOTA en pose variada (CFP-FP), entrenado
    # con augmentación masiva de ángulo: ideal para fotos de rescate (3/4, perfil).
    # Cada foto registrada genera además augmentaciones por rotación (±15°).
    embedding_dim: int = 512
    match_threshold: float = 0.55  # distancia coseno por debajo = coincidencia
    min_face_quality: float = 0.50  # det_score mínimo de InsightFace (0–1)
    confidence_sigmoid_k: float = 12.0  # pendiente de la curva de confianza
    confidence_sigmoid_midpoint: float = 0.40  # distancia donde la confianza = 50 %

    # Superadmin — BOOTSTRAP únicamente.
    # `admin_user` / `admin_password` SÓLO se usan la primera vez para sembrar la tabla
    # `admins` desde env vars (ver main.lifespan). El login real valida SIEMPRE contra
    # la BD con hash bcrypt. Cambiá la password con `python -m app.cli change-password`.
    admin_user: str = "admin"
    admin_password: str = ""

    # JWT firmado para los endpoints de admin.
    # >>> JWT_SECRET DEBE estar setteado en producción (generá uno con
    #     `python -c "import secrets; print(secrets.token_urlsafe(64))"`).
    # Si está vacío, el server falla al arrancar con un mensaje claro.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60

    @property
    def endpoint_url(self) -> str:
        """Endpoint S3 del Space; se deriva de la región si no se define."""
        return (
            self.spaces_endpoint
            or f"https://{self.spaces_region}.digitaloceanspaces.com"
        )

    @property
    def public_base_url(self) -> str:
        """Base pública para construir la URL de cada imagen subida."""
        if self.spaces_cdn_endpoint:
            return self.spaces_cdn_endpoint.rstrip("/")
        return (
            f"https://{self.spaces_bucket}.{self.spaces_region}.digitaloceanspaces.com"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
