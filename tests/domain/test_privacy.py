"""Tests for MenoresPrivacy domain module."""

from datetime import datetime

from app.domain.privacy import MenoresPrivacy
from app.schemas import AlertaFamiliar, Candidato, PersonaAdmin


class TestCandidatoPrivacy:
    """Tests for MenoresPrivacy with Candidato objects."""

    def test_masks_candidato_minor(self):
        """Minor Candidato should have nombre/apellido masked to None."""
        candidato = Candidato(
            person_id="test-id",
            estado="encontrada",
            image_url="http://example.com/img.jpg",
            distancia=0.3,
            coincidencia=75,
            confianza="media",
            es_menor=True,
            nombre="Juan",
            apellido="Pérez",
            refugio=None,
            ubicacion=None,
            telefono=None,
        )
        masked = MenoresPrivacy(candidato)
        assert masked.nombre is None
        assert masked.apellido is None

    def test_passes_candidato_adult(self):
        """Adult Candidato should keep nombre/apellido unchanged."""
        candidato = Candidato(
            person_id="test-id",
            estado="encontrada",
            image_url="http://example.com/img.jpg",
            distancia=0.3,
            coincidencia=75,
            confianza="media",
            es_menor=False,
            nombre="Rosa",
            apellido="López",
            refugio=None,
            ubicacion=None,
            telefono=None,
        )
        result = MenoresPrivacy(candidato)
        assert result.nombre == "Rosa"
        assert result.apellido == "López"

    def test_original_not_mutated_candidato(self):
        """Original Candidato should not be mutated."""
        candidato = Candidato(
            person_id="test-id",
            estado="encontrada",
            image_url="http://example.com/img.jpg",
            distancia=0.3,
            coincidencia=75,
            confianza="media",
            es_menor=True,
            nombre="Juan",
            apellido="Pérez",
            refugio=None,
            ubicacion=None,
            telefono=None,
        )
        _ = MenoresPrivacy(candidato)
        assert candidato.nombre == "Juan"
        assert candidato.apellido == "Pérez"


class TestAlertaFamiliarPrivacy:
    """Tests for MenoresPrivacy with AlertaFamiliar objects."""

    def test_masks_alerta_familiar_minor(self):
        """Minor AlertaFamiliar should have familiar_nombre masked to None."""
        alerta = AlertaFamiliar(
            person_id="test-id",
            image_url="http://example.com/img.jpg",
            coincidencia=75,
            confianza="media",
            es_menor=True,
            familiar_nombre="Ana",
        )
        masked = MenoresPrivacy(alerta)
        assert masked.familiar_nombre is None

    def test_passes_alerta_familiar_adult(self):
        """Adult AlertaFamiliar should keep familiar_nombre unchanged."""
        alerta = AlertaFamiliar(
            person_id="test-id",
            image_url="http://example.com/img.jpg",
            coincidencia=75,
            confianza="media",
            es_menor=False,
            familiar_nombre="Carlos",
        )
        result = MenoresPrivacy(alerta)
        assert result.familiar_nombre == "Carlos"


class TestPersonaAdminPrivacy:
    """Tests for MenoresPrivacy with PersonaAdmin objects."""

    def test_masks_persona_admin_minor(self):
        """Minor PersonaAdmin should have nombre/apellido masked to None."""
        persona = PersonaAdmin(
            person_id="test-id",
            estado="buscada",
            es_menor=True,
            nombre="María",
            apellido="García",
            fotos=["http://example.com/img1.jpg"],
            created_at=datetime.now(),
        )
        masked = MenoresPrivacy(persona)
        assert masked.nombre is None
        assert masked.apellido is None

    def test_passes_persona_admin_adult(self):
        """Adult PersonaAdmin should keep nombre/apellido unchanged."""
        persona = PersonaAdmin(
            person_id="test-id",
            estado="buscada",
            es_menor=False,
            nombre="Pedro",
            apellido="Martínez",
            fotos=["http://example.com/img1.jpg"],
            created_at=datetime.now(),
        )
        result = MenoresPrivacy(persona)
        assert result.nombre == "Pedro"
        assert result.apellido == "Martínez"


class TestEdgeCases:
    """Tests for edge cases."""

    def test_none_names_stay_none(self):
        """Candidato with None names should not error."""
        candidato = Candidato(
            person_id="test-id",
            estado="encontrada",
            image_url="http://example.com/img.jpg",
            distancia=0.3,
            coincidencia=75,
            confianza="media",
            es_menor=True,
            nombre=None,
            apellido=None,
            refugio=None,
            ubicacion=None,
            telefono=None,
        )
        masked = MenoresPrivacy(candidato)
        assert masked.nombre is None
        assert masked.apellido is None
