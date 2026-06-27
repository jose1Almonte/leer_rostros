"""Tests for MatchingPolicy domain module."""

import sys
import types

import pytest

from app.domain.matching import MatchingPolicy


@pytest.fixture(autouse=True)
def _mock_faces_module(monkeypatch):
    """Insert mock app.faces module to avoid cv2/insightface import in tests.

    match_percentage() does a lazy `from app import faces` which would trigger
    `import cv2` at module level. We pre-insert a mock module in sys.modules
    so the lazy import resolves to our mock without touching cv2.
    """
    if "app.faces" not in sys.modules:
        mock_faces = types.ModuleType("app.faces")
        object.__setattr__(
            mock_faces, "distance_to_confidence", lambda d: 50.0
        )  # default
        monkeypatch.setitem(sys.modules, "app.faces", mock_faces)


class TestIsMatch:
    """Tests for MatchingPolicy.is_match() method."""

    def test_is_match_below_threshold(self, policy: MatchingPolicy):
        """Distance below threshold should return True."""
        assert policy.is_match(0.45)

    def test_is_match_at_threshold(self, policy: MatchingPolicy):
        """Distance at threshold should return False (strict <)."""
        assert not policy.is_match(0.55)

    def test_is_match_above_threshold(self, policy: MatchingPolicy):
        """Distance above threshold should return False."""
        assert not policy.is_match(0.60)

    def test_is_match_zero_distance(self, policy: MatchingPolicy):
        """Zero distance (identical embeddings) should return True."""
        assert policy.is_match(0.0)

    def test_custom_threshold(self):
        """Custom threshold should work correctly."""
        custom_policy = MatchingPolicy(threshold=0.30)
        assert custom_policy.is_match(0.25)
        assert not custom_policy.is_match(0.35)


class TestConfidenceBand:
    """Tests for MatchingPolicy.confidence_band() method."""

    def test_confidence_band_alta(self, policy: MatchingPolicy):
        """Distance below conf_alta should return 'alta'."""
        assert policy.confidence_band(0.30) == "alta"

    def test_confidence_band_media(self, policy: MatchingPolicy):
        """Distance between conf_alta and conf_media should return 'media'."""
        assert policy.confidence_band(0.45) == "media"

    def test_confidence_band_baja(self, policy: MatchingPolicy):
        """Distance above conf_media should return 'baja'."""
        assert policy.confidence_band(0.60) == "baja"

    def test_confidence_band_at_alta_boundary(self, policy: MatchingPolicy):
        """Distance at conf_alta boundary should return 'media' (strict <)."""
        assert policy.confidence_band(0.40) == "media"

    def test_confidence_band_at_media_boundary(self, policy: MatchingPolicy):
        """Distance at conf_media boundary should return 'baja' (strict <)."""
        assert policy.confidence_band(0.55) == "baja"


class TestMatchPercentage:
    """Tests for MatchingPolicy.match_percentage() method.

    Note: match_percentage delegates to faces.distance_to_confidence (sigmoid).
    These tests mock the sigmoid to verify the delegation and int() truncation.
    """

    def test_match_percentage_zero(self, policy: MatchingPolicy, monkeypatch):
        """Zero distance should return 100%."""
        faces_mod = sys.modules["app.faces"]
        monkeypatch.setattr(
            faces_mod, "distance_to_confidence", lambda d: 100.0 if d == 0.0 else 50.0
        )
        assert policy.match_percentage(0.0) == 100

    def test_match_percentage_at_threshold(self, policy: MatchingPolicy, monkeypatch):
        """Distance at threshold should return ~16%."""
        # Mock sigmoid: at distance=0.55 with k=12, midpoint=0.40
        # sigmoid = 100 / (1 + exp(12 * (0.55 - 0.40))) ≈ 16%
        faces_mod = sys.modules["app.faces"]
        monkeypatch.setattr(faces_mod, "distance_to_confidence", lambda d: 16.0)
        assert policy.match_percentage(0.55) == 16

    def test_match_percentage_large_distance(self, policy: MatchingPolicy, monkeypatch):
        """Large distance should return ~0%."""
        faces_mod = sys.modules["app.faces"]
        monkeypatch.setattr(faces_mod, "distance_to_confidence", lambda d: 0.1)
        assert policy.match_percentage(2.0) == 0

    def test_match_percentage_typical(self, policy: MatchingPolicy, monkeypatch):
        """Typical distance should return expected percentage."""
        # At distance=0.36, sigmoid should give ~62%
        faces_mod = sys.modules["app.faces"]
        monkeypatch.setattr(faces_mod, "distance_to_confidence", lambda d: 62.0)
        assert policy.match_percentage(0.36) == 62
