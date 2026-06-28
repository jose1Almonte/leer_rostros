"""Tests for RegistrarTestimonio use case."""

import sys
import types
from uuid import uuid4

import pytest

from app.testimonios.use_cases import RegistrarTestimonio
from app.shared._exceptions import (
    ArchivoInvalidoError,
    PersonaNotFoundError,
    PersonaValidationError,
)
from tests.testimonios.use_cases.fake import FakeTestimonioRepository


@pytest.fixture(autouse=True)
def _mock_storage(monkeypatch):
    """Mock app.storage.upload_file to avoid filesystem writes."""
    if "app.storage" not in sys.modules:
        mock = types.ModuleType("app.storage")
        monkeypatch.setitem(sys.modules, "app.storage", mock)
    mod = sys.modules["app.storage"]
    monkeypatch.setattr(
        mod,
        "upload_file",
        lambda data, key, ct: f"https://fake-cdn.example.com/{key}",
        raising=False,
    )


@pytest.fixture
def fake_repo():
    return FakeTestimonioRepository()


@pytest.fixture
def use_case(fake_repo):
    return RegistrarTestimonio(fake_repo)


class TestRegistrarTestimonioHappyPath:
    def test_happy_path_with_person_id(self, use_case, fake_repo):
        """Valid upload with person_id creates pending testimonio."""
        pid = uuid4()
        fake_repo._existing_person_ids.add(str(pid))
        result = use_case.execute(
            archivo_data=b"fake-image-bytes",
            content_type="image/jpeg",
            person_id=str(pid),
        )
        assert result["estado"] == "pendiente"
        assert result["tipo"] == "foto"
        assert result["person_id"] == str(pid)

    def test_happy_path_video(self, use_case, fake_repo):
        """MP4 video upload is accepted."""
        pid = uuid4()
        fake_repo._existing_person_ids.add(str(pid))
        result = use_case.execute(
            archivo_data=b"fake-video-bytes",
            content_type="video/mp4",
            person_id=str(pid),
        )
        assert result["estado"] == "pendiente"
        assert result["tipo"] == "video"

    def test_happy_path_without_person_id(self, use_case):
        """Valid upload without person_id requires nombre + contacto."""
        result = use_case.execute(
            archivo_data=b"fake-image-bytes",
            content_type="image/webp",
            person_id=None,
            nombre_testigo="María Pérez",
            contacto_testigo="0412-1234567",
            mensaje="¡Lo encontramos gracias a esta app!",
        )
        assert result["estado"] == "pendiente"
        assert result["person_id"] is None
        assert result["tipo"] == "foto"

    def test_happy_path_with_all_fields(self, use_case, fake_repo):
        """All optional fields are stored properly."""
        pid = uuid4()
        fake_repo._existing_person_ids.add(str(pid))
        result = use_case.execute(
            archivo_data=b"fake-image-bytes",
            content_type="image/jpeg",
            person_id=str(pid),
            mensaje="Gracias totales",
            nombre_testigo="Juan López",
            contacto_testigo="juan@email.com",
        )
        assert result["estado"] == "pendiente"
        assert result["person_id"] == str(pid)

    def test_png_is_accepted(self, use_case, fake_repo):
        """PNG image is accepted."""
        pid = uuid4()
        fake_repo._existing_person_ids.add(str(pid))
        result = use_case.execute(
            archivo_data=b"fake-png-bytes",
            content_type="image/png",
            person_id=str(pid),
        )
        assert result["tipo"] == "foto"

    def test_webm_is_accepted(self, use_case, fake_repo):
        """WebM video is accepted."""
        pid = uuid4()
        fake_repo._existing_person_ids.add(str(pid))
        result = use_case.execute(
            archivo_data=b"fake-webm-bytes",
            content_type="video/webm",
            person_id=str(pid),
        )
        assert result["tipo"] == "video"


class TestRegistrarTestimonioValidation:
    def test_raises_archivo_invalido_empty(self, use_case):
        """Empty data → ArchivoInvalidoError."""
        with pytest.raises(ArchivoInvalidoError) as exc_info:
            use_case.execute(
                archivo_data=b"",
                content_type="image/jpeg",
                person_id=None,
                nombre_testigo="Test",
                contacto_testigo="0412-1111111",
            )
        assert "archivo" in str(exc_info.value).lower()

    def test_raises_archivo_invalido_too_large(self, use_case):
        """Data > 50MB → ArchivoInvalidoError."""
        big_data = b"x" * (50 * 1024 * 1024 + 1)
        with pytest.raises(ArchivoInvalidoError) as exc_info:
            use_case.execute(
                archivo_data=big_data,
                content_type="image/jpeg",
                person_id=None,
                nombre_testigo="Test",
                contacto_testigo="0412-1111111",
            )
        assert "50 MB" in str(exc_info.value)

    def test_raises_archivo_invalido_bad_mime(self, use_case):
        """Unsupported content-type → ArchivoInvalidoError."""
        with pytest.raises(ArchivoInvalidoError) as exc_info:
            use_case.execute(
                archivo_data=b"some-data",
                content_type="application/pdf",
                person_id=None,
                nombre_testigo="Test",
                contacto_testigo="0412-1111111",
            )
        assert "formato" in str(exc_info.value).lower()

    def test_raises_persona_not_found_invalid_uuid(self, use_case):
        """Invalid person_id UUID → PersonaValidationError."""
        with pytest.raises(PersonaValidationError) as exc_info:
            use_case.execute(
                archivo_data=b"data",
                content_type="image/jpeg",
                person_id="not-a-uuid",
            )
        assert "person_id" in str(exc_info.value).lower()

    def test_raises_persona_not_found_nonexistent(self, use_case):
        """Well-formed person_id but doesn't exist → PersonaNotFoundError."""
        with pytest.raises(PersonaNotFoundError):
            use_case.execute(
                archivo_data=b"data",
                content_type="image/jpeg",
                person_id=str(uuid4()),
            )

    def test_raises_no_person_id_and_no_nombre(self, use_case):
        """Missing person_id AND nombre_testigo → PersonaValidationError."""
        with pytest.raises(PersonaValidationError) as exc_info:
            use_case.execute(
                archivo_data=b"data",
                content_type="image/jpeg",
                person_id=None,
                nombre_testigo=None,
                contacto_testigo="0412-1111111",
            )
        assert "nombre" in str(exc_info.value).lower()

    def test_raises_no_person_id_and_no_contacto(self, use_case):
        """Missing person_id AND contacto_testigo → PersonaValidationError."""
        with pytest.raises(PersonaValidationError) as exc_info:
            use_case.execute(
                archivo_data=b"data",
                content_type="image/jpeg",
                person_id=None,
                nombre_testigo="Test",
                contacto_testigo=None,
            )
        assert "contacto" in str(exc_info.value).lower()


class TestRegistrarTestimonioRepoIntegration:
    def test_testimonio_stored_with_pendiente(self, use_case, fake_repo):
        """Testimonio starts in 'pendiente' state."""
        pid = uuid4()
        fake_repo._existing_person_ids.add(str(pid))
        use_case.execute(
            archivo_data=b"data",
            content_type="image/jpeg",
            person_id=str(pid),
        )
        stored = fake_repo._testimonios[0]
        assert stored["estado"] == "pendiente"
        assert stored["archivo_key"].startswith("testimonios/")

    def test_testimonio_stored_without_person_id(self, use_case, fake_repo):
        """Testimonio without person_id stores None."""
        use_case.execute(
            archivo_data=b"data",
            content_type="image/jpeg",
            person_id=None,
            nombre_testigo="Test",
            contacto_testigo="0412-1111111",
            mensaje="Mensaje test",
        )
        stored = fake_repo._testimonios[0]
        assert stored["person_id"] is None
        assert stored["mensaje"] == "Mensaje test"
        assert stored["nombre_testigo"] == "Test"
