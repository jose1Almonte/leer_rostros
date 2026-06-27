from datetime import datetime

from pydantic import BaseModel, Field


class PersonaOut(BaseModel):
    """Persona registrada en el sistema."""

    id: str = Field(..., description="Identificador único de la persona.", examples=["3ad0cfd3-a08e-4c97-8cc5-1785051d09f0"])
    nombre: str | None = Field(None, description="Nombre de la persona (opcional).", examples=["José Pérez"])
    ci: str | None = Field(None, description="Cédula o documento de identidad (opcional).", examples=["V-12345678"])
    rol: str | None = Field(None, description="Rol o nota libre (p. ej. quién reporta).", examples=[None])
    estado: str = Field(..., description="Estado: 'buscada' (un familiar la busca) o 'encontrada' (un rescatista la halló).", examples=["desaparecida"])
    image_url: str = Field(..., description="URL pública de la foto principal en el bucket.", examples=["https://flowcheckapp.sfo3.digitaloceanspaces.com/personas/3ad0cfd3.jpg"])
    created_at: datetime = Field(..., description="Fecha y hora de registro (UTC).")


class Coincidencia(PersonaOut):
    """Persona candidata devuelta por una búsqueda, con su grado de similitud."""

    distancia: float = Field(..., description="Distancia coseno entre el rostro buscado y el mejor embedding registrado. Menor = más parecido (0 = idéntico).", examples=[0.256])
    confianza: float = Field(..., description="Porcentaje de confianza (0–100 %) derivado de la distancia mediante una sigmoide calibrada. >70 % = alta confianza; 30–70 % = revisar; <30 % = baja confianza.", examples=[85.4])
    calidad_rostro: float = Field(..., description="Puntuación de detección del mejor embedding registrado (0–1). Valores bajos indican foto de registro con ángulo extremo o poca iluminación.", examples=[0.94])
    es_match: bool = Field(..., description="True si la distancia está por debajo del umbral de coincidencia.", examples=[True])


class FotosAgregadasOut(BaseModel):
    """Confirmación de fotos adicionales agregadas a una persona ya registrada."""

    persona_id: str = Field(..., description="ID de la persona a quien se agregaron las fotos.")
    embeddings_agregados: int = Field(..., description="Cantidad de vectores faciales insertados (foto base + augmentaciones exitosas).")


class ResultadoBusqueda(BaseModel):
    """Resultado de una búsqueda facial: candidatos ordenados por parecido."""

    umbral: float = Field(..., description="Umbral de coincidencia usado. Una distancia menor que este valor se considera match.", examples=[0.55])
    coincidencias: list[Coincidencia] = Field(..., description="Candidatos ordenados del más parecido (menor distancia) al menos parecido.")
