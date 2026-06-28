from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class TipoTestimonio(str, Enum):
    FOTO = "foto"
    VIDEO = "video"


class TestimonioBase(BaseModel):
    id: UUID
    person_id: UUID | None = None
    tipo: TipoTestimonio
    archivo_url: str
    archivo_key: str
    mime: str
    bytes: int
    mensaje: str | None = None
    nombre_testigo: str | None = None
    contacto_testigo: str | None = None
    estado: str = "pendiente"
    created_at: datetime | None = None
