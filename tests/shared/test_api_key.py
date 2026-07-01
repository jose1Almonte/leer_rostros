import pytest
from fastapi import HTTPException
from fastapi.datastructures import URL
from app.auth import verify_api_key
from app.config import get_settings


class DummyRequest:
    def __init__(self, path: str):
        self.url = URL(f"http://testserver{path}")


def test_exempt_paths():
    # Verify that exempt paths return the api_key value back without errors or checking
    for path in [
        "/health",
        "/admin/login",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/admin/personas",
    ]:
        req = DummyRequest(path)
        # Even if API key is missing or invalid, it should be accepted/bypassed
        assert verify_api_key(req, api_key=None) is None
        assert verify_api_key(req, api_key="invalid") == "invalid"


def test_missing_api_key():
    req = DummyRequest("/buscados")
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(req, api_key=None)
    assert exc_info.value.status_code == 403
    assert "missing" in exc_info.value.detail.lower()


def test_invalid_api_key(monkeypatch):
    # Set up settings with mock API keys
    settings = get_settings()
    monkeypatch.setattr(settings, "api_keys", "key1,key2")

    req = DummyRequest("/buscados")
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(req, api_key="key3")
    assert exc_info.value.status_code == 403
    assert "invalid" in exc_info.value.detail.lower()


def test_valid_api_key(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "api_keys", "key1,key2")

    req = DummyRequest("/buscados")
    assert verify_api_key(req, api_key="key1") == "key1"
    assert verify_api_key(req, api_key="key2") == "key2"
