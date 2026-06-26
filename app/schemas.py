from datetime import datetime

from pydantic import BaseModel


class PersonaOut(BaseModel):
    id: str
    nombre: str | None = None
    ci: str | None = None
    rol: str | None = None
    estado: str
    image_url: str
    created_at: datetime


class Coincidencia(PersonaOut):
    distancia: float
    es_match: bool


class ResultadoBusqueda(BaseModel):
    umbral: float
    coincidencias: list[Coincidencia]
