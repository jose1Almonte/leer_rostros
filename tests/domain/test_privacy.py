"""Tests para MenoresPrivacy (passthrough: ya NO se enmascara a los menores).

Decisión de producto: para reunificación en catástrofe, el nombre del menor SÍ se
muestra (o null si no se conoce). MenoresPrivacy devuelve el objeto sin cambios.
"""

from datetime import datetime

from app.domain.privacy import MenoresPrivacy
from app.schemas import AlertaFamiliar, Candidato, PersonaAdmin


class TestCandidatoPrivacy:
    def test_minor_candidato_keeps_name(self):
        """Un menor AHORA conserva nombre/apellido (ya no se enmascara)."""
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
        result = MenoresPrivacy(candidato)
        assert result.nombre == "Juan"
        assert result.apellido == "Pérez"

    def test_minor_low_coincidencia_masked(self):
        """Menor con coincidencia < 20 % → se ocultan nombre/apellido."""
        candidato = Candidato(
            person_id="test-id",
            estado="encontrada",
            image_url="http://example.com/img.jpg",
            distancia=0.7,
            coincidencia=10,
            confianza="baja",
            es_menor=True,
            nombre="Juan",
            apellido="Pérez",
            refugio=None,
            ubicacion=None,
            telefono=None,
        )
        result = MenoresPrivacy(candidato)
        assert result.nombre is None
        assert result.apellido is None

    def test_adult_low_coincidencia_keeps_name(self):
        """Adulto con coincidencia baja → NO se enmascara (solo aplica a menores)."""
        candidato = Candidato(
            person_id="test-id",
            estado="encontrada",
            image_url="http://example.com/img.jpg",
            distancia=0.7,
            coincidencia=10,
            confianza="baja",
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

    def test_adult_candidato_keeps_name(self):
        """Un adulto conserva nombre/apellido (sin cambios)."""
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

    def test_none_names_stay_none(self):
        """Sin nombre → sigue null (el front muestra 'Sin nombre registrado')."""
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
        result = MenoresPrivacy(candidato)
        assert result.nombre is None
        assert result.apellido is None


class TestAlertaFamiliarPrivacy:
    def test_minor_alerta_keeps_name(self):
        alerta = AlertaFamiliar(
            person_id="test-id",
            image_url="http://example.com/img.jpg",
            coincidencia=75,
            confianza="media",
            es_menor=True,
            familiar_nombre="Ana",
        )
        result = MenoresPrivacy(alerta)
        assert result.familiar_nombre == "Ana"


class TestPersonaAdminPrivacy:
    def test_minor_persona_admin_keeps_name(self):
        persona = PersonaAdmin(
            person_id="test-id",
            estado="buscada",
            es_menor=True,
            nombre="María",
            apellido="García",
            fotos=["http://example.com/img1.jpg"],
            created_at=datetime.now(),
        )
        result = MenoresPrivacy(persona)
        assert result.nombre == "María"
        assert result.apellido == "García"
