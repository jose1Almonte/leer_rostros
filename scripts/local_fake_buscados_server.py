"""Local fake server for manually testing /buscados pagination.

This serves the static frontend and a small in-memory API under /api.
It does not connect to Postgres, DigitalOcean Spaces, or InsightFace.
"""

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw

from app.domain.matching import MatchingPolicy
from app.domain.persona import Estado, PersonaBase
from app.personas.use_cases import ListarCoincidenciasBusqueda, RegistrarBusqueda
from app.schemas import ResultadoBusqueda
from tests.personas.repositories.fake import FakePersonaRepository

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
FAKE_DATA_DIR = ROOT / "output" / "local_fake_data"
FOTOS_DIR = FAKE_DATA_DIR / "fotos"
PERSONAS_DIR = FOTOS_DIR / "personas"
QUERY_IMAGE = FAKE_DATA_DIR / "query.png"

app = FastAPI(title="Local fake /buscados pagination tester")


def _patch_confidence() -> None:
    """Avoid loading the real InsightFace model during fake tests."""
    from app import faces

    faces.distance_to_confidence = lambda distance: max(
        0.0, min(100.0, round(100.0 - (distance * 120.0), 1))
    )


def _make_avatar(path: Path, index: int, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bg = (
        45 + (index * 37) % 150,
        65 + (index * 29) % 130,
        90 + (index * 17) % 120,
    )
    img = Image.new("RGB", (360, 360), bg)
    draw = ImageDraw.Draw(img)
    skin = (228, 180, 135)
    hair = (45 + (index * 11) % 80, 35 + (index * 7) % 70, 30 + (index * 5) % 60)
    draw.ellipse((95, 55, 265, 235), fill=skin)
    draw.pieslice((75, 35, 285, 185), 180, 360, fill=hair)
    draw.ellipse((140, 130, 158, 148), fill=(20, 25, 35))
    draw.ellipse((202, 130, 220, 148), fill=(20, 25, 35))
    draw.arc((145, 150, 220, 205), 20, 160, fill=(110, 50, 55), width=4)
    draw.rectangle((105, 245, 255, 355), fill=(25, 35, 60))
    draw.text((16, 18), label, fill=(255, 255, 255))
    img.save(path)


def _prepare_fake_images() -> None:
    PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(1, 24):
        _make_avatar(PERSONAS_DIR / f"fake-{i:02d}.png", i, f"Persona {i:02d}")
    _make_avatar(QUERY_IMAGE, 99, "Busqueda")


def _build_repo() -> FakePersonaRepository:
    policy = MatchingPolicy(threshold=0.55)
    repo = FakePersonaRepository(policy=policy)
    for i in range(1, 24):
        persona = PersonaBase(
            person_id=uuid4(),
            estado=Estado.ENCONTRADA,
            es_menor=i % 7 == 0,
            nombre=f"Persona {i:02d}",
            apellido="Demo",
            edad=str(18 + (i % 50)),
            refugio=f"Refugio Demo {(i % 5) + 1}",
            ubicacion=f"Zona de prueba {(i % 8) + 1}",
            telefono_responsable=f"0414-000-{i:04d}",
            encontrado_por="Equipo local",
            descripcion="Registro sintetico para prueba local.",
            moderacion="aprobada",
            photos=[f"/fotos/personas/fake-{i:02d}.png"],
        )
        repo._personas.append(persona)
    return repo


_patch_confidence()
_prepare_fake_images()
_repo = _build_repo()
_policy = MatchingPolicy(threshold=0.55)


async def _fake_procesar_fotos(files: list[UploadFile]):
    processed = []
    for file in files:
        data = await file.read()
        if data:
            processed.append(
                (data, file.content_type or "image/png", [(b"fake-query-embedding", 0.99)])
            )
    return processed


@app.post("/api/buscados", response_model=ResultadoBusqueda, status_code=201)
async def registrar_busqueda(
    files: list[UploadFile] = File(...),
    nombre: str | None = Form(None),
    apellido: str | None = Form(None),
    edad: str | None = Form(None),
    doc_tipo: str | None = Form(None),
    doc_numero: str | None = Form(None),
    telefono_contacto: str | None = Form(None),
    limite: int = Form(10),
    limit: int | None = Form(None),
    offset: int = Form(0),
    page: int | None = Form(None),
):
    use_case = RegistrarBusqueda(_repo, _policy)
    limite_final = limit if limit is not None else limite
    return use_case.execute(
        procesadas=await _fake_procesar_fotos(files),
        nombre=nombre,
        apellido=apellido,
        edad=edad,
        doc_tipo=doc_tipo,
        doc_numero=doc_numero,
        telefono_contacto=telefono_contacto,
        limite=limite_final,
        offset=offset,
        page=page,
    )


@app.get("/api/buscados/{codigo}/coincidencias", response_model=ResultadoBusqueda)
def listar_coincidencias_busqueda(
    codigo: str,
    limite: int | None = Query(None),
    limit: int | None = Query(None),
    offset: int = Query(0),
    page: int | None = Query(None),
):
    use_case = ListarCoincidenciasBusqueda(_repo)
    limite_final = limit if limit is not None else (limite if limite is not None else 10)
    return use_case.execute(
        codigo=codigo,
        limite=limite_final,
        offset=offset,
        page=page,
    )


app.mount("/fotos", StaticFiles(directory=FOTOS_DIR), name="fotos")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
