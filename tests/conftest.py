"""Pytest configuration and shared fixtures."""

# Standard library
import sys
from pathlib import Path
from uuid import uuid4

# Third-party
import pytest
from fastapi.testclient import TestClient

# Local
from app.auth import Admin
from app.domain.matching import MatchingPolicy

# Ensure app/ imports work when running pytest from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def policy():
    """Default MatchingPolicy with production threshold (0.55)."""
    return MatchingPolicy(threshold=0.55)


@pytest.fixture
def admin():
    """Dummy Admin instance for dependency override."""
    return Admin(
        id=uuid4(),
        username="testadmin",
        is_active=True,
    )


@pytest.fixture
def admin_token():
    """Valid Bearer token string for admin endpoint tests."""
    return "Bearer test-jwt-token"


@pytest.fixture
def admin_headers(admin_token):
    """Headers dict with Authorization Bearer token."""
    return {"Authorization": admin_token}


@pytest.fixture
def client(admin):
    """FastAPI TestClient with auth dependency override.

    Does NOT start lifespan (no DB/DeepFace boot).
    Override get_current_admin to return a dummy Admin.
    """
    from app.auth import get_current_admin
    from app.main import app

    # Override the auth dependency
    async def override_get_current_admin():
        return admin

    app.dependency_overrides[get_current_admin] = override_get_current_admin

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    # Cleanup
    app.dependency_overrides.clear()
