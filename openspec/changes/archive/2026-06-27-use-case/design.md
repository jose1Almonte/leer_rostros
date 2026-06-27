# Design: `use-case` — Extract Use Cases from `app/main.py`

## 0. Executive Summary

This design extracts six use-case classes from the monolithic `app/main.py` (515 lines) into a dedicated `app/use_cases/` module. Each business flow (`POST /buscados`, `POST /encontrados`, `POST /buscar`, `GET /admin/personas`, `PATCH .../moderacion`, `DELETE .../{id}`) becomes a single, named class with an `execute()` method. Endpoints become thin HTTP adapters (≤20 lines) that parse requests, call the use case, catch domain exceptions, and return Pydantic response models. `PersonaRepository.add` signature changes from `dict` to `PersonaBase`. An in-memory `FakePersonaRepository` at `tests/repositories/fake.py` enables unit testing without PostgreSQL or InsightFace. No behavioral changes — this is a mechanical extraction.

---

## 1. Module Map

```
app/
  use_cases/
    __init__.py              # Barrel — exports all use case classes
    _exceptions.py           # Domain exceptions (PersonaValidationError, etc.)
    registrar_busqueda.py    # RegistrarBusqueda class
    registrar_encontrado.py  # RegistrarEncontrado class (with cross-flow alert)
    buscar_admin.py          # BuscarAdmin class
    listar_personas_admin.py # ListarPersonasAdmin class
    moderar_persona.py       # ModerarPersona class
    eliminar_persona.py      # EliminarPersona class
  ...                        # existing modules unchanged

tests/
  use_cases/
    __init__.py
    test_registrar_busqueda.py
    test_registrar_encontrado.py
    test_buscar_admin.py
    test_listar_personas_admin.py
    test_moderar_persona.py
    test_eliminar_persona.py
  repositories/
    __init__.py
    fake.py                  # FakePersonaRepository
```

---

## 2. Domain Exceptions

**File**: `app/use_cases/_exceptions.py`

```python
"""Domain exceptions raised by use cases.

Use cases raise these exceptions; endpoints catch them and map to HTTP status codes.
Each exception carries a `message` attribute used as the HTTPException detail.
"""


class PersonaValidationError(Exception):
    """Raised when form data fails business validation (422)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class RostroNoDetectadoError(Exception):
    """Raised when no face is detected in uploaded photo(s) (422)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class PersonaNotFoundError(Exception):
    """Raised when a person_id does not exist in the database (404)."""

    def __init__(self, message: str = "No existe esa persona"):
        self.message = message
        super().__init__(message)


class ModificacionInvalidaError(Exception):
    """Raised when an invalid moderation value is provided (400)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
```

---

## 3. Public Interfaces

### 3.1 `RegistrarBusqueda`

**File**: `app/use_cases/registrar_busqueda.py`

```python
from uuid import UUID, uuid4

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.domain.privacy import MenoresPrivacy
from app.repositories.persona import PersonaRepository
from app.schemas import Candidato, ResultadoBusqueda
from app.use_cases._exceptions import PersonaValidationError, RostroNoDetectadoError


# Type alias for processed photos (same shape as current _procesar_fotos output)
# (image_bytes, content_type, [(embedding_array, calidad_score), ...])
ProcessedPhotos = list[tuple[bytes, str, list[tuple[Any, float]]]]

LIMITE_MAX = 50


class RegistrarBusqueda:
    """FAMILIAR flow: register a missing-person search and return top matches."""

    def __init__(self, repo: PersonaRepository, policy: MatchingPolicy):
        self._repo = repo
        self._policy = policy

    def execute(
        self,
        *,
        procesadas: ProcessedPhotos,
        nombre: str | None,
        apellido: str | None,
        edad: str | None,
        doc_tipo: str | None,
        doc_numero: str | None,
        telefono_contacto: str | None,
        limite: int,
    ) -> ResultadoBusqueda:
        """Register a missing-person search and return ranked candidates.

        Args:
            procesadas: List of processed photos with embeddings (from _procesar_fotos).
            nombre: Person's first name (optional, but required if doc_numero absent).
            apellido: Person's last name.
            edad: Age as string.
            doc_tipo: Document type (e.g., "V").
            doc_numero: Document number (required if nombre absent).
            telefono_contacto: Contact phone for reunification.
            limite: Maximum candidates to return (clamped to 1–50).

        Returns:
            ResultadoBusqueda with codigo, total, and coincidencias.

        Raises:
            RostroNoDetectadoError: If no faces detected in any photo.
            PersonaValidationError: If neither nombre nor doc_numero provided.
        """
        # Validation
        if not procesadas:
            raise RostroNoDetectadoError(
                "No se detectó ningún rostro en la(s) foto(s)."
            )
        if not (doc_numero or (nombre and nombre.strip())):
            raise PersonaValidationError(
                "Indica al menos el nombre o el número de identificación."
            )

        limite = max(1, min(LIMITE_MAX, limite))

        # Build domain object
        person_id = uuid4()
        codigo = _gen_codigo()

        persona = PersonaBase(
            person_id=person_id,
            estado=Estado.BUSCADA,
            es_menor=False,
            nombre=nombre,
            apellido=apellido,
            edad=edad,
            doc_tipo=doc_tipo,
            doc_numero=doc_numero,
            telefono_contacto=telefono_contacto,
            moderacion="aprobada",
        )

        # Persist
        self._repo.add(person_id, persona, procesadas)

        # Search
        embedding = _embedding_consulta(procesadas)
        encontrados = self._repo.search_by_estado(embedding, "encontrada", limite)

        # Apply privacy and build response
        candidatos = [MenoresPrivacy(Candidato(**d)) for d in encontrados]
        return ResultadoBusqueda(
            codigo=codigo,
            total=len(candidatos),
            coincidencias=candidatos,
        )
```

### 3.2 `RegistrarEncontrado`

**File**: `app/use_cases/registrar_encontrado.py`

```python
from uuid import UUID, uuid4

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.domain.privacy import MenoresPrivacy
from app.repositories.persona import PersonaRepository
from app.schemas import AlertaFamiliar, ResultadoRegistro
from app.use_cases._exceptions import PersonaValidationError, RostroNoDetectadoError


class RegistrarEncontrado:
    """RESCATISTA flow: register a found person, alert if a family match exists."""

    def __init__(self, repo: PersonaRepository, policy: MatchingPolicy):
        self._repo = repo
        self._policy = policy

    def execute(
        self,
        *,
        procesadas: ProcessedPhotos,
        es_menor: bool,
        nombre: str | None,
        apellido: str | None,
        doc_tipo: str | None,
        doc_numero: str | None,
        refugio: str | None,
        ubicacion: str | None,
        telefono_responsable: str | None,
        doc_responsable: str | None,
        descripcion: str | None,
    ) -> ResultadoRegistro:
        """Register a found person and return registration result with optional alert.

        Validation rules:
        1. At least one photo with a detected face.
        2. refugio is required.
        3. telefono_responsable is required.
        4. If es_menor=True, doc_responsable is required.

        Returns:
            ResultadoRegistro with codigo, person_id, and optional alerta.

        Raises:
            RostroNoDetectadoError: If no faces detected.
            PersonaValidationError: If required fields are missing.
        """
        # Validation
        if not procesadas:
            raise RostroNoDetectadoError(
                "No se detectó ningún rostro en la(s) foto(s)."
            )
        if not refugio or not refugio.strip():
            raise PersonaValidationError("El refugio actual es obligatorio.")
        if not telefono_responsable or not telefono_responsable.strip():
            raise PersonaValidationError(
                "El teléfono del responsable es obligatorio."
            )
        if es_menor and not (doc_responsable and doc_responsable.strip()):
            raise PersonaValidationError(
                "Para un menor, la identificación del responsable es obligatoria."
            )

        # Build domain object
        person_id = uuid4()
        codigo = _gen_codigo()

        persona = PersonaBase(
            person_id=person_id,
            estado=Estado.ENCONTRADA,
            es_menor=es_menor,
            nombre=nombre,
            apellido=apellido,
            doc_tipo=doc_tipo,
            doc_numero=doc_numero,
            refugio=refugio,
            ubicacion=ubicacion,
            telefono_responsable=telefono_responsable,
            doc_responsable=doc_responsable,
            descripcion=descripcion,
            moderacion="pendiente",  # Found persons start pending moderation
        )

        # Persist
        self._repo.add(person_id, persona, procesadas)

        # Cross-flow search for matching buscada
        embedding = _embedding_consulta(procesadas)
        buscados = self._repo.search_by_estado(embedding, "buscada", 1)

        # Build alert if match exists
        alerta = None
        if buscados:
            best = buscados[0]
            d = best["distancia"]
            if self._policy.is_match(d):
                alerta = AlertaFamiliar(
                    person_id=best["person_id"],
                    familiar_nombre=best["nombre"],
                    familiar_telefono=best["telefono"],
                    image_url=best["image_url"],
                    coincidencia=best["coincidencia"],
                    confianza=best["confianza"],
                    es_menor=best["es_menor"],
                )
                alerta = MenoresPrivacy(alerta)

        return ResultadoRegistro(
            codigo=codigo,
            person_id=str(person_id),
            alerta=alerta,
        )
```

### 3.3 `BuscarAdmin`

**File**: `app/use_cases/buscar_admin.py`

```python
from app.domain.privacy import MenoresPrivacy
from app.repositories.persona import PersonaRepository
from app.schemas import Candidato


class BuscarAdmin:
    """ADMIN flow: compare a photo against the entire database."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(
        self,
        *,
        embedding: Any,
        estado: str | None,
        limite: int,
    ) -> list[Candidato]:
        """Search the database for matching candidates (no moderation filter).

        Args:
            embedding: Query embedding vector (from faces.embedding_from_bytes).
            estado: Optional filter ("buscada" or "encontrada").
            limite: Maximum results (clamped to 1–50).

        Returns:
            List of Candidato with privacy masking applied.
        """
        limite = max(1, min(LIMITE_MAX, limite))
        results = self._repo.search_admin(embedding, estado, limite)
        return [MenoresPrivacy(Candidato(**d)) for d in results]
```

### 3.4 `ListarPersonasAdmin`

**File**: `app/use_cases/listar_personas_admin.py`

```python
from app.domain.privacy import MenoresPrivacy
from app.repositories.persona import PersonaRepository
from app.schemas import PersonaAdmin


class ListarPersonasAdmin:
    """ADMIN flow: list all registered personas with optional filters."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(
        self,
        *,
        limite: int,
        estado: str | None,
        moderacion: str | None,
    ) -> list[PersonaAdmin]:
        """List personas for admin view.

        Returns:
            List of PersonaAdmin with privacy masking applied.
        """
        results = self._repo.list_admin(limite, estado, moderacion)
        return [MenoresPrivacy(PersonaAdmin(**d)) for d in results]
```

### 3.5 `ModerarPersona`

**File**: `app/use_cases/moderar_persona.py`

```python
from app.repositories.persona import PersonaRepository
from app.use_cases._exceptions import ModificacionInvalidaError, PersonaNotFoundError


VALID_MODERACION = ("aprobada", "rechazada", "pendiente")


class ModerarPersona:
    """ADMIN flow: update moderation status for a persona."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(self, *, person_id: str, valor: str) -> dict:
        """Update moderation status for all rows with the given person_id.

        Args:
            person_id: UUID string of the persona to moderate.
            valor: New moderation value ("aprobada", "rechazada", or "pendiente").

        Returns:
            Dict with person_id, moderacion, and fotos_actualizadas count.

        Raises:
            ModificacionInvalidaError: If valor is not a valid moderation value.
            PersonaNotFoundError: If person_id does not exist.
        """
        if valor not in VALID_MODERACION:
            raise ModificacionInvalidaError(
                "valor debe ser 'aprobada', 'rechazada' o 'pendiente'"
            )

        n = self._repo.set_moderacion(person_id, valor)
        if not n:
            raise PersonaNotFoundError("No existe esa persona")

        return {
            "person_id": person_id,
            "moderacion": valor,
            "fotos_actualizadas": n,
        }
```

### 3.6 `EliminarPersona`

**File**: `app/use_cases/eliminar_persona.py`

```python
from app.repositories.persona import PersonaRepository
from app.use_cases._exceptions import PersonaNotFoundError


class EliminarPersona:
    """ADMIN flow: delete a persona and its associated images."""

    def __init__(self, repo: PersonaRepository):
        self._repo = repo

    def execute(self, *, person_id: str) -> dict:
        """Delete a persona and all its photos.

        Args:
            person_id: UUID string of the persona to delete.

        Returns:
            Dict with person_id, eliminada=True, and fotos count.

        Raises:
            PersonaNotFoundError: If person_id does not exist.
        """
        fotos = self._repo.delete(person_id)
        if not fotos:
            raise PersonaNotFoundError("No existe esa persona")

        return {
            "person_id": person_id,
            "eliminada": True,
            "fotos": fotos,
        }
```

### 3.7 Shared helpers

**File**: `app/use_cases/_helpers.py` (internal to the module)

```python
"""Shared helpers used across use cases."""

import uuid


def _gen_codigo() -> str:
    """Generate a unique registration code (e.g., 'REE-A1B2C3D4')."""
    return "REE-" + uuid.uuid4().hex[:8].upper()


def _embedding_consulta(procesadas):
    """Get the base embedding from the first processed photo for search queries."""
    return procesadas[0][2][0][0] if procesadas else None
```

### 3.8 Barrel module

**File**: `app/use_cases/__init__.py`

```python
"""Use-case layer — one class per business flow."""

from app.use_cases.buscar_admin import BuscarAdmin
from app.use_cases.eliminar_persona import EliminarPersona
from app.use_cases.listar_personas_admin import ListarPersonasAdmin
from app.use_cases.moderar_persona import ModerarPersona
from app.use_cases.registrar_busqueda import RegistrarBusqueda
from app.use_cases.registrar_encontrado import RegistrarEncontrado

__all__ = [
    "BuscarAdmin",
    "EliminarPersona",
    "ListarPersonasAdmin",
    "ModerarPersona",
    "RegistrarBusqueda",
    "RegistrarEncontrado",
]
```

---

## 4. Endpoint Refactor

After extraction, each endpoint in `app/main.py` becomes a thin HTTP adapter. The face-processing helpers (`_procesar_fotos`, `_embedding_consulta`) remain in the endpoint module since they deal with FastAPI `UploadFile`. A helper for exception mapping eliminates repetitive try/except blocks.

### 4.1 Exception mapping helper

```python
# app/main.py — new helper

from functools import wraps
from fastapi import HTTPException
from app.use_cases._exceptions import (
    PersonaValidationError,
    RostroNoDetectadoError,
    PersonaNotFoundError,
    ModificacionInvalidaError,
)


def _map_use_case_errors(func):
    """Decorator that maps domain exceptions to HTTP status codes."""
    _STATUS_MAP = {
        PersonaValidationError: 422,
        RostroNoDetectadoError: 422,
        PersonaNotFoundError: 404,
        ModificacionInvalidaError: 400,
    }

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            status = _STATUS_MAP.get(type(exc))
            if status is not None:
                raise HTTPException(status, exc.message) from None
            raise
    return wrapper
```

For sync endpoints, a sync variant is also provided (or use the same decorator since it handles both sync and async functions via `inspect.iscoroutinefunction`).

### 4.2 Refactored endpoints

```python
# POST /buscados
@app.post("/buscados", response_model=ResultadoBusqueda, status_code=201, tags=["familiar"])
async def registrar_busqueda(
    files: list[UploadFile] = File(...),
    nombre: str | None = Form(None),
    apellido: str | None = Form(None),
    edad: str | None = Form(None),
    doc_tipo: str | None = Form(None),
    doc_numero: str | None = Form(None),
    telefono_contacto: str | None = Form(None),
    limite: int = Form(10),
):
    procesadas = await _procesar_fotos(files)
    use_case = RegistrarBusqueda(get_repo(), get_policy())
    return await use_case_execute(
        use_case.execute,
        procesadas=procesadas, nombre=nombre, apellido=apellido,
        edad=edad, doc_tipo=doc_tipo, doc_numero=doc_numero,
        telefono_contacto=telefono_contacto, limite=limite,
    )
```

Where `use_case_execute` is a helper that wraps the sync `execute` call inside the try/except:

```python
async def _use_case_execute(execute_fn, **kwargs):
    """Call a sync use case execute() with domain exception mapping."""
    try:
        return execute_fn(**kwargs)
    except PersonaValidationError as e:
        raise HTTPException(422, e.message) from None
    except RostroNoDetectadoError as e:
        raise HTTPException(422, e.message) from None
    except PersonaNotFoundError as e:
        raise HTTPException(404, e.message) from None
    except ModificacionInvalidaError as e:
        raise HTTPException(400, e.message) from None
```

All six endpoints follow the same pattern:

```python
# POST /encontrados  (~12 lines)
@app.post("/encontrados", response_model=ResultadoRegistro, status_code=201, tags=["rescatista"])
async def registrar_encontrado(...):
    procesadas = await _procesar_fotos(files)
    use_case = RegistrarEncontrado(get_repo(), get_policy())
    return await _use_case_execute(use_case.execute, procesadas=procesadas, es_menor=es_menor, ...)

# POST /buscar  (~8 lines)
@app.post("/buscar", response_model=list[Candidato], tags=["admin"], dependencies=[...])
async def buscar_admin(file: UploadFile = File(...), limite: int = Form(25), estado: str | None = Form(None)):
    data = await file.read()
    try:
        embedding, _ = faces.embedding_from_bytes(data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    use_case = BuscarAdmin(get_repo())
    return await _use_case_execute(use_case.execute, embedding=embedding, estado=estado, limite=limite)

# GET /admin/personas  (~5 lines)
@app.get("/admin/personas", response_model=list[PersonaAdmin], tags=["admin"], dependencies=[...])
def listar(limite: int = 100, estado: str | None = None, moderacion: str | None = None):
    use_case = ListarPersonasAdmin(get_repo())
    return _use_case_execute_sync(use_case.execute, limite=limite, estado=estado, moderacion=moderacion)

# PATCH .../moderacion  (~6 lines)
@app.patch("/admin/personas/{person_id}/moderacion", tags=["admin"], dependencies=[...])
def moderar(person_id: str, valor: str):
    use_case = ModerarPersona(get_repo())
    return _use_case_execute_sync(use_case.execute, person_id=person_id, valor=valor)

# DELETE .../{person_id}  (~5 lines)
@app.delete("/admin/personas/{person_id}", tags=["admin"], dependencies=[...])
def eliminar(person_id: str):
    use_case = EliminarPersona(get_repo())
    return _use_case_execute_sync(use_case.execute, person_id=person_id)
```

**Result**: Each endpoint is ≤20 lines. `admin_login` stays as-is (~22 lines) since it does not touch `PersonaRepository`.

---

## 5. PersonaRepository.add Signature Change

**File**: `app/repositories/persona.py`

### 5.1 New signature

```python
def add(
    self,
    person_id: UUID,
    persona: PersonaBase,          # CHANGED from dict[str, Any]
    procesadas: list[tuple[bytes, str, list[tuple[Any, float]]]],
) -> list[str]:
    """Insert one row per photo into personas + N embeddings per photo.

    Args:
        person_id: UUID grouping all photos.
        persona: PersonaBase domain object with all fields.
        procesadas: list of (image_data, content_type, [(embedding, calidad), ...]).

    Returns:
        List of uploaded image URLs.
    """
    urls = []
    with self._pool.connection() as conn:
        for data, ct, embs in procesadas:
            ext = CONTENT_EXT.get(ct, "jpg")
            foto_id = uuid.uuid4()
            key = f"personas/{foto_id}.{ext}"
            url = storage.upload_image(data, key, ct)

            # Map PersonaBase fields to SQL parameter names
            datos = {
                "estado": persona.estado.value,       # "buscada" or "encontrada"
                "menor": persona.es_menor,            # es_menor → menor column
                "nombre": persona.nombre,
                "apellido": persona.apellido,
                "edad": persona.edad,
                "doc_tipo": persona.doc_tipo,
                "doc_numero": persona.doc_numero,
                "tel_contacto": persona.telefono_contacto,
                "refugio": persona.refugio,
                "tel_resp": persona.telefono_responsable,
                "doc_resp": persona.doc_responsable,
                "descripcion": persona.descripcion,
                "ubicacion": persona.ubicacion,
                "codigo": persona.codigo,
                # SQL-specific fields
                "id": foto_id,
                "pid": person_id,
                "url": url,
                "key": key,
            }

            conn.execute(self._INSERT_PERSONA, datos)
            for emb, calidad in embs:
                conn.execute(self._INSERT_EMBEDDING, (foto_id, emb, calidad))
            conn.commit()
            urls.append(url)
    return urls
```

### 5.2 Key changes

- The `datos` dict is now constructed **inside the repository** from `PersonaBase` fields, not in the endpoint or use case.
- SQL parameter naming convention (`menor`, `tel_contacto`, `tel_resp`) stays encapsulated in the repository.
- `persona.estado.value` converts the `Estado` enum to its string value for SQL.
- Fields not relevant to a particular flow (e.g., `telefono_contacto` for encontrados) are `None` on the `PersonaBase` and stored as NULL.

---

## 6. In-Memory Fake Repository

**File**: `tests/repositories/fake.py`

```python
"""In-memory fake implementation of PersonaRepository for use case unit tests.

This fake implements the same public interface as PersonaRepository but stores
data in Python lists. It is fully deterministic and configurable for testing.

IMPORTANT: This is test-only infrastructure. Do NOT import from app/ code.
"""

import uuid
from typing import Any
from uuid import UUID

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.schemas import Candidato, PersonaAdmin


class FakePersonaRepository:
    """In-memory fake of PersonaRepository.

    Supports:
    - add(): stores persona and generates fake embeddings
    - search_by_estado(): returns stored personas ranked by fake distance
    - search_admin(): same as search_by_estado, no moderation filter
    - list_admin(): returns stored personas as PersonaAdmin-shaped dicts
    - set_moderacion(): updates moderacion on stored personas
    - delete(): removes personas by person_id
    """

    def __init__(self, policy: MatchingPolicy | None = None):
        self._policy = policy or MatchingPolicy(threshold=0.55)
        self._personas: list[PersonaBase] = []
        self._embeddings: dict[str, list[bytes]] = {}  # person_id -> list of fake embeddings
        self._deleted: list[str] = []

    def add(
        self,
        person_id: UUID,
        persona: PersonaBase,
        procesadas: list[tuple[bytes, str, list[tuple[Any, float]]]],
    ) -> list[str]:
        """Store persona and generate fake image URLs."""
        persona.photos = []
        for _data, ct, _embs in procesadas:
            foto_id = uuid.uuid4()
            url = f"https://fake-cdn.example.com/personas/{foto_id}.{ct.split('/')[-1]}"
            persona.photos.append(url)
        self._personas.append(persona)
        return persona.photos

    def search_by_estado(
        self, embedding: Any, estado: str | None, limit: int
    ) -> list[dict]:
        """Return stored personas filtered by estado, with fake distances.

        Simulates a cosine-distance search by assigning ascending distances
        to stored personas (0.10, 0.20, 0.30, ...) so that policy.is_match
        can be tested predictably.
        """
        candidates = [
            p for p in self._personas
            if p.moderacion == "aprobada" and (estado is None or p.estado.value == estado)
        ]
        results = []
        for i, persona in enumerate(candidates[:limit]):
            distancia = round(0.10 * (i + 1), 4)
            results.append(self._to_candidato_dict(persona, distancia))
        return results

    def search_admin(
        self, embedding: Any, estado: str | None, limit: int
    ) -> list[dict]:
        """Same as search_by_estado but no moderacion filter."""
        candidates = [
            p for p in self._personas
            if estado is None or p.estado.value == estado
        ]
        results = []
        for i, persona in enumerate(candidates[:limit]):
            distancia = round(0.10 * (i + 1), 4)
            results.append(self._to_candidato_dict(persona, distancia))
        return results

    def list_admin(
        self, limit: int, estado: str | None = None, moderacion: str | None = None
    ) -> list[dict]:
        """Return stored personas as PersonaAdmin-shaped dicts."""
        results = []
        for persona in self._personas:
            if estado and persona.estado.value != estado:
                continue
            if moderacion and persona.moderacion != moderacion:
                continue
            results.append(self._to_admin_dict(persona))
            if len(results) >= limit:
                break
        return results

    def set_moderacion(self, person_id: str, valor: str) -> int:
        """Update moderacion for all personas with the given person_id."""
        count = 0
        for persona in self._personas:
            if str(persona.person_id) == person_id:
                # PersonaBase is immutable (frozen BaseModel with model_copy)
                # We replace the entry in the list
                idx = self._personas.index(persona)
                updated = persona.model_copy(update={"moderacion": valor})
                self._personas[idx] = updated
                count += 1
        return count

    def delete(self, person_id: str) -> int:
        """Delete personas by person_id. Returns number of photos deleted."""
        original_count = len(self._personas)
        self._personas = [
            p for p in self._personas if str(p.person_id) != person_id
        ]
        deleted_count = original_count - len(self._personas)
        if deleted_count > 0:
            self._deleted.append(person_id)
        return deleted_count

    # -- Internal helpers --

    def _to_candidato_dict(self, persona: PersonaBase, distancia: float) -> dict:
        """Convert PersonaBase to a Candidato-shaped dict."""
        distancia = float(distancia)
        return {
            "person_id": str(persona.person_id),
            "estado": persona.estado.value,
            "es_menor": persona.es_menor,
            "nombre": persona.nombre,
            "apellido": persona.apellido,
            "edad": persona.edad,
            "refugio": persona.refugio,
            "ubicacion": persona.ubicacion or persona.refugio,
            "telefono": persona.telefono_responsable or persona.telefono_contacto,
            "descripcion": persona.descripcion,
            "image_url": persona.photos[0] if persona.photos else "",
            "distancia": distancia,
            "coincidencia": self._policy.match_percentage(distancia),
            "confianza": self._policy.confidence_band(distancia),
        }

    def _to_admin_dict(self, persona: PersonaBase) -> dict:
        """Convert PersonaBase to a PersonaAdmin-shaped dict."""
        return {
            "person_id": str(persona.person_id),
            "estado": persona.estado.value,
            "es_menor": persona.es_menor,
            "nombre": persona.nombre,
            "apellido": persona.apellido,
            "edad": persona.edad,
            "doc": persona.doc_numero,
            "refugio": persona.refugio,
            "ubicacion": persona.ubicacion,
            "telefono": persona.telefono_responsable or persona.telefono_contacto,
            "codigo": persona.codigo,
            "moderacion": persona.moderacion,
            "fotos": persona.photos,
            "created_at": None,  # Not tracked in fake
        }
```

### 6.1 Fake design principles

- **Fully in-memory**: No DB, no InsightFace. Pure Python lists and dicts.
- **Deterministic**: `search_*` methods assign predictable distances (0.10, 0.20, ...) so tests can assert on `policy.is_match` behavior without real embeddings.
- **Configurable**: Constructor accepts an optional `MatchingPolicy` for threshold tuning.
- **Inspectable**: `_personas` list is accessible for post-condition assertions (e.g., "assert repo.add was called with a PersonaBase with es_menor=True").
- **Interface-matched**: Same method signatures as `PersonaRepository` (same param types, return types).

---

## 7. Test Strategy

### 7.1 `test_registrar_busqueda.py`

| Test | What it verifies |
|------|-----------------|
| `test_happy_path_with_nombre` | Name provided, returns ResultadoBusqueda with matches |
| `test_happy_path_with_doc_numero` | doc_numero provided (no name), returns matches |
| `test_raises_rostro_no_detectado` | Empty procesadas → RostroNoDetectadoError |
| `test_raises_persona_validation_no_name_no_doc` | Neither nombre nor doc_numero → PersonaValidationError |
| `test_limite_clamped_to_1` | limite=0 → clamped to 1 |
| `test_limite_clamped_to_50` | limite=100 → clamped to 50 |
| `test_applies_menores_privacy_on_candidates` | Minor candidates have nombre=None, apellido=None |
| `test_adult_names_preserved` | Adult candidates have real names |
| `test_repo_add_called_with_persona_base_not_dict` | Assert repo received a PersonaBase instance |
| `test_repo_add_called_with_estado_buscada` | PersonaBase.estado == Estado.BUSCADA |
| `test_repo_add_called_with_moderacion_aprobada` | PersonaBase.moderacion == "aprobada" |
| `test_empty_search_returns_zero_total` | No matches in repo → total=0, empty coincidencias |
| `test_codigo_is_generated` | Result has a codigo starting with "REE-" |

### 7.2 `test_registrar_encontrado.py`

| Test | What it verifies |
|------|-----------------|
| `test_happy_path_no_match` | Valid registration, no cross-match, alerta=None |
| `test_happy_path_with_match` | Cross-match exists, alerta is populated |
| `test_alerta_menor_masks_nombre` | Match is minor, alerta.familiar_nombre is None |
| `test_alerta_non_minor_preserves_nombre` | Match is adult, alerta.familiar_nombre has value |
| `test_minor_name_stored_not_nulled` | Minor's nombre is stored in persona, only masked in response |
| `test_raises_rostro_no_detectado` | Empty procesadas → RostroNoDetectadoError |
| `test_raises_persona_validation_no_refugio` | Missing refugio → PersonaValidationError |
| `test_raises_persona_validation_no_telefono_responsable` | Missing telefono_responsable → PersonaValidationError |
| `test_raises_persona_validation_menor_sin_doc_responsable` | es_menor=True, no doc_responsable → PersonaValidationError |
| `test_repo_add_called_with_estado_encontrada` | PersonaBase.estado == Estado.ENCONTRADA |
| `test_repo_add_called_with_moderacion_pendiente` | PersonaBase.moderacion == "pendiente" |
| `test_repo_add_called_with_es_menor_true` | PersonaBase.es_menor matches input |

### 7.3 `test_buscar_admin.py`

| Test | What it verifies |
|------|-----------------|
| `test_happy_path_returns_candidates` | Valid embedding returns list of Candidato |
| `test_limite_clamped` | limite=0 → 1, limite=100 → 50 |
| `test_filters_by_estado` | estado="buscada" returns only buscada |
| `test_applies_menores_privacy` | Minor candidates masked |
| `test_no_moderacion_filter` | Admin search returns all moderacion statuses |

### 7.4 `test_listar_personas_admin.py`

| Test | What it verifies |
|------|-----------------|
| `test_happy_path_returns_personas` | Returns list of PersonaAdmin |
| `test_filters_by_estado` | estado filter works |
| `test_filters_by_moderacion` | moderacion filter works |
| `test_applies_menores_privacy` | Minor personas masked |
| `test_respects_limite` | Returns at most `limit` results |
| `test_empty_list_when_no_data` | Returns [] when fake repo is empty |

### 7.5 `test_moderar_persona.py`

| Test | What it verifies |
|------|-----------------|
| `test_happy_path_aprobada` | Valid valor → returns dict with fotos_actualizadas |
| `test_happy_path_rechazada` | Same for "rechazada" |
| `test_happy_path_pendiente` | Same for "pendiente" |
| `test_raises_modificacion_invalida` | valor="invalido" → ModificacionInvalidaError |
| `test_raises_persona_not_found` | Non-existent person_id → PersonaNotFoundError |
| `test_exception_has_message` | Error message matches expected string |

### 7.6 `test_eliminar_persona.py`

| Test | What it verifies |
|------|-----------------|
| `test_happy_path_deletes_persona` | Valid person_id → returns dict with fotos count |
| `test_raises_persona_not_found` | Non-existent person_id → PersonaNotFoundError |
| `test_persona_removed_from_fake` | After delete, persona no longer in repo |
| `test_exception_has_message` | Error message matches expected string |

### 7.7 Coverage target

- **≥80% line coverage** on `app/use_cases/` via `pytest --cov=app/use_cases --cov-report=term-missing`.
- Existing 22 domain tests must continue to pass (`pytest tests/domain/`).

---

## 8. Rollout Plan

### 8.1 Pre-deploy checklist

- [ ] All use case unit tests pass (≥6 new test files)
- [ ] Existing domain tests pass (22 tests, 100% coverage on `app/domain/`)
- [ ] Coverage ≥80% on `app/use_cases/`
- [ ] Manual smoke test: `POST /buscados` with valid photo returns `ResultadoBusqueda`
- [ ] Manual smoke test: `POST /encontrados` with valid photo returns `ResultadoRegistro`
- [ ] Manual smoke test: Admin endpoints return same shapes as before

### 8.2 Deploy

Standard `docker-compose up -d`. No database migrations, no schema changes, no new environment variables.

### 8.3 Post-deploy

- Smoke test all 6 affected endpoints through the live API.
- Monitor error logs for any `PersonaValidationError` or `RostroNoDetectadoError` that weren't caught before (indicates a behavioral change).

### 8.4 Rollback

If the change breaks production:

1. Revert the PR (restores `app/main.py` to pre-refactor state).
2. Remove `app/use_cases/` directory.
3. Revert `app/repositories/persona.py` `add` signature to accept `dict`.
4. Remove new tests under `tests/use_cases/` and `tests/repositories/fake.py`.
5. **No database changes** — safe to revert code only.

---

## 9. Open Questions / Risks for the Implementer

### 9.1 Sync vs async use case methods

**Decision**: Use case `execute()` methods are **synchronous**. The endpoint handles async file reading (`await file.read()`) and passes processed data (bytes, embeddings) to the use case. The `_procesar_fotos` helper remains in `app/main.py` since it deals with FastAPI `UploadFile`. Use case tests never touch `UploadFile`.

The `_use_case_execute` helper in `app/main.py` wraps the sync call in a try/except for domain exception mapping.

### 9.2 UploadFile vs bytes at the use case boundary

**Decision**: The use case interface takes `ProcessedPhotos` (a `list[tuple[bytes, str, list[tuple[np.ndarray, float]]]]`), not `UploadFile`. The endpoint reads `await file.read()` and passes the raw bytes. This keeps the use case framework-agnostic and testable.

### 9.3 `_procesar_fotos` location

**Decision**: Face embedding extraction (`faces.embeddings_from_bytes`, InsightFace/TensorFlow loading) stays in `app/main.py` as `_procesar_fotos`. This is the HTTP boundary. The use case receives already-processed embeddings. Abstracting face processing behind an interface (FaceEmbedder seam) is **out of scope** — it's a future change.

### 9.4 Shared helpers location

**Decision**: `_gen_codigo()` and `_embedding_consulta()` are extracted to `app/use_cases/_helpers.py` and used by use cases. The endpoint versions in `app/main.py` can delegate to these or keep their own copies (both are fine; `_gen_codigo` is 1 line).

### 9.5 `ProcessedPhotos` type alias

**Decision**: Define a `ProcessedPhotos` type alias in the use case module (or `_helpers.py`) so all use cases share the same type. This avoids repeating the verbose tuple signature:

```python
# Same shape as _procesar_fotos output
ProcessedPhotos = list[tuple[bytes, str, list[tuple[np.ndarray, float]]]]
```

### 9.6 Fake repository and MatchingPolicy

**Decision**: The fake's `search_by_estado` and `search_admin` methods assign **ascending fake distances** (0.10, 0.20, 0.30, ...) to stored personas. This ensures:

- First candidate has distance 0.10 → `policy.is_match(0.10)` returns True (0.10 < 0.55).
- Sixth candidate has distance 0.60 → `policy.is_match(0.60)` returns False.
- Tests can predict which candidates will match and which won't, without real embeddings.

### 9.7 `_map_use_case_errors` vs per-endpoint try/except

**Decision**: Use a single `_use_case_execute` helper function (async) and `_use_case_execute_sync` (sync) that wraps the try/except block. This eliminates repetitive exception mapping across 6 endpoints. Alternative: a decorator. The function approach is preferred because some endpoints need pre-processing (e.g., `faces.embedding_from_bytes` in `buscar_admin`) before calling the use case.

### 9.8 Estimated changed lines

| Area | Added | Removed | Modified |
|------|-------|---------|----------|
| `app/use_cases/` (7 new files) | ~250 | — | — |
| `app/main.py` (refactored endpoints) | ~60 | ~200 | ~40 |
| `app/repositories/persona.py` (add refactor) | ~20 | ~10 | ~10 |
| `tests/use_cases/` (6 test files) | ~350 | — | — |
| `tests/repositories/fake.py` | ~120 | — | — |
| **Total** | **~800** | **~210** | **~50** |

Net: ~590 lines changed. Within the 800-line review budget. Likely **one PR**.

---

## 10. Data Flow

```
Endpoint (app/main.py)
  │
  ├─ async: reads UploadFile → await _procesar_fotos() → procesadas (bytes + embeddings)
  ├─ sync: reads query/path params
  │
  ▼
Use Case (app/use_cases/*.py)
  │
  ├─ Validates inputs → raises domain exceptions on failure
  ├─ Constructs PersonaBase from form fields
  ├─ Calls repo.add(person_id, persona, procesadas)
  ├─ Calls repo.search_* / repo.list_admin / repo.set_moderacion / repo.delete
  ├─ Applies MenoresPrivacy to results
  ├─ Assembles Pydantic response model
  │
  ▼
Endpoint returns Pydantic model → FastAPI serializes to JSON
```

For `RegistrarEncontrado`, an additional step after `repo.add`:

```
  ├─ repo.search_by_estado(embedding, "buscada", 1)
  ├─ policy.is_match(distance) → if True, build AlertaFamiliar
  ├─ MenoresPrivacy(alerta) if match is a minor
```
