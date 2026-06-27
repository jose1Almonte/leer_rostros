from datetime import datetime

from pydantic import BaseModel, Field


class PersonaOut(BaseModel):
    """Persona registrada en el sistema."""

    id: str = Field(..., description="Identificador único de la persona.", examples=["3ad0cfd3-a08e-4c97-8cc5-1785051d09f0"])
    nombre: str | None = Field(None, description="Nombre de la persona (opcional).", examples=["José Pérez"])
    ci: str | None = Field(None, description="Cédula o documento de identidad (opcional).", examples=["V-12345678"])
    rol: str | None = Field(None, description="Rol o nota libre (p. ej. quién reporta).", examples=[None])
    estado: str = Field(..., description="Estado: 'buscada' (un familiar la busca) o 'encontrada' (un rescatista la halló).", examples=["desaparecida"])
    image_url: str = Field(..., description="URL pública de la foto en el bucket de almacenamiento.", examples=["https://flowcheckapp.sfo3.digitaloceanspaces.com/personas/3ad0cfd3.jpg"])
    created_at: datetime = Field(..., description="Fecha y hora de registro (UTC).")


class Coincidencia(PersonaOut):
    """Persona candidata devuelta por una búsqueda, con su grado de similitud."""

    distancia: float = Field(..., description="Distancia coseno entre el rostro buscado y este registro. Menor = más parecido (0 = idéntico).", examples=[0.256])
    es_match: bool = Field(..., description="True si la distancia está por debajo del umbral de coincidencia (alta confianza).", examples=[True])


class ResultadoBusqueda(BaseModel):
    """Resultado de una búsqueda facial: candidatos ordenados por parecido."""

    umbral: float = Field(..., description="Umbral de coincidencia usado. Una distancia menor que este valor se considera match.", examples=[0.55])
    coincidencias: list[Coincidencia] = Field(..., description="Candidatos ordenados del más parecido (menor distancia) al menos parecido.")
