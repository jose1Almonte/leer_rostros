"""Tests del guard anti-SSRF en app.shared._net.

No hacen red real: se mockea socket.getaddrinfo para simular a qué IP resuelve un host.
"""

import socket

import pytest

from app.shared._net import _ip_es_publica, validar_url_publica


def _fake_getaddrinfo(ip: str):
    """Devuelve un getaddrinfo falso que resuelve cualquier host a `ip`."""
    def _inner(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]
    return _inner


# --- _ip_es_publica ---

@pytest.mark.parametrize("ip", [
    "169.254.169.254",  # metadata cloud (AWS/GCP/DO link-local)
    "127.0.0.1",        # loopback
    "10.0.0.5",         # privada
    "172.16.3.4",       # privada
    "192.168.1.1",      # privada
    "0.0.0.0",          # unspecified
    "::1",              # loopback IPv6
    "fd00::1",          # ULA IPv6
])
def test_ip_interna_no_es_publica(ip):
    assert _ip_es_publica(ip) is False


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_ip_externa_es_publica(ip):
    assert _ip_es_publica(ip) is True


# --- validar_url_publica ---

def test_rechaza_esquema_no_http():
    with pytest.raises(ValueError, match="http/https"):
        validar_url_publica("file:///etc/passwd")
    with pytest.raises(ValueError, match="http/https"):
        validar_url_publica("gopher://x/")


def test_rechaza_sin_host():
    with pytest.raises(ValueError, match="host"):
        validar_url_publica("http://")


def test_rechaza_metadata_cloud(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(ValueError, match="no permitida"):
        validar_url_publica("http://metadata.attacker.com/latest/meta-data/")


def test_rechaza_localhost(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))
    with pytest.raises(ValueError, match="no permitida"):
        validar_url_publica("http://localhost:5432/")


def test_rechaza_red_privada(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("10.1.2.3"))
    with pytest.raises(ValueError, match="no permitida"):
        validar_url_publica("https://interno.lan/foto.jpg")


def test_rechaza_host_irresoluble(monkeypatch):
    def _boom(*a, **k):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(ValueError, match="resolver"):
        validar_url_publica("https://no-existe-jamas.invalid/x.jpg")


def test_acepta_url_publica(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert validar_url_publica("https://example.com/foto.jpg") == "example.com"
