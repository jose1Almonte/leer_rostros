"""Configuración del add-on, cargada desde variables de entorno / .env.

Se mantiene SEPARADA de app.config.Settings para no tocar el núcleo. El umbral de
match y la database_url se siguen leyendo de app.config (única fuente de verdad)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AddonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Canal de envío del cron nocturno ---
    # Preferencia: si MATCH_NOTIFY_WEBHOOK_URL está seteado, el cron postea cada match a
    # ese webhook n8n (que se encarga del WhatsApp). Si no, usa Evolution API directo.
    # Si NINGUNO está configurado, el cron solo detecta y deja los matches en 'pendiente'.
    match_notify_webhook_url: str = ""   # ej. https://TU-N8N/webhook/reencuentros-match-notify

    # --- Evolution API (fallback directo, si no usas n8n) ---
    evolution_url: str = ""          # ej. https://evo.midominio.com  (sin / final)
    evolution_apikey: str = ""       # apikey global o de la instancia
    evolution_instance: str = ""     # nombre de la instancia de WhatsApp
    evolution_timeout: int = 20      # segundos (cron / envío)
    evolution_interactive_timeout: int = 6   # timeout corto para QR/estado en el panel
    qr_cache_ttl: int = 25           # seg: reusar el QR en /qr para no re-disparar connect()

    # --- WhatsApp / normalización de teléfonos ---
    # Código de país por defecto (sin '+') para números locales sin prefijo.
    # Venezuela = 58. Cámbialo según el país de operación.
    wa_default_country: str = "58"
    wa_business_name: str = "Reencuentros"

    # --- Barrido de matches ---
    # Cuántas buscadas procesar por corrida del cron (0 = todas).
    addon_scan_limite: int = 0
    # Coincidencia mínima (0-100) para AVISAR. La detección usa el umbral de distancia
    # de MatchingPolicy; esto es un filtro extra anti-falsos-positivos para el aviso.
    # 80 = solo avisar matches muy probables, para revisión humana.
    addon_min_coincidencia_aviso: int = 80
    # Reintentos máximos de una notificación 'fallida' (falla transitoria) en el cron.
    addon_max_reintentos: int = 5

    @property
    def evolution_enabled(self) -> bool:
        return bool(
            self.evolution_url and self.evolution_apikey and self.evolution_instance
        )


@lru_cache
def get_addon_settings() -> AddonSettings:
    return AddonSettings()
