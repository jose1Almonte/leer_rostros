"""Descarga de imágenes desde URLs externas con protección anti-SSRF.

El endpoint de importación descarga la foto desde una `foto_url` que provee el
cliente (admin). Sin validar el destino, un admin comprometido podría apuntar a
servicios internos: metadata de la nube (`169.254.169.254`), Postgres en
`127.0.0.1:5432`, o cualquier host de la red privada (SSRF + pivote).

`validar_url_publica` resuelve el host y exige que TODAS sus IPs sean públicas.
`descargar_imagen_segura` revalida en cada redirección (evita el bypass por 302 a
una IP interna) y corta la descarga si excede el tamaño máximo.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

# Tope de descarga (alineado con client_max_body_size de nginx).
MAX_DESCARGA_BYTES = 15 * 1024 * 1024
_MAX_REDIRECTS = 3
_ESQUEMAS_OK = ("http", "https")


def _ip_es_publica(ip_str: str) -> bool:
    """True solo si la IP es enrutable en internet (no privada/loopback/link-local/reservada)."""
    ip = ipaddress.ip_address(ip_str)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validar_url_publica(url: str) -> str:
    """Valida el esquema y que el host resuelva SOLO a IPs públicas. Devuelve el host.

    Lanza `ValueError` si el esquema no es http/https, el host no resuelve, o alguna
    de sus IPs cae en un rango interno (169.254.x, 127.x, 10/172.16/192.168, ULA IPv6…).
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ESQUEMAS_OK:
        raise ValueError("Solo se permiten URLs http/https.")
    host = parsed.hostname
    if not host:
        raise ValueError("URL sin host válido.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or None)
    except socket.gaierror as e:
        raise ValueError(f"No se pudo resolver el host: {host}") from e
    ips = {info[4][0] for info in infos}
    if not ips:
        raise ValueError(f"No se pudo resolver el host: {host}")
    for ip in ips:
        if not _ip_es_publica(ip):
            raise ValueError(f"La URL apunta a una IP no permitida ({ip}).")
    return host


def descargar_imagen_segura(url: str, *, user_agent: str = "reencuentros-importer") -> bytes:
    """Descarga una imagen validando contra SSRF en cada salto.

    - Revalida esquema + IP pública en cada redirección (máx 3), cerrando el bypass 302.
    - Corta la descarga si supera `MAX_DESCARGA_BYTES`.
    """
    actual = url
    for _ in range(_MAX_REDIRECTS + 1):
        validar_url_publica(actual)
        r = requests.get(
            actual,
            timeout=25,
            headers={"User-Agent": user_agent},
            allow_redirects=False,
            stream=True,
        )
        try:
            if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
                destino = r.headers.get("Location")
                if not destino:
                    raise ValueError("Redirección sin destino.")
                actual = urljoin(actual, destino)
                continue
            r.raise_for_status()
            total = 0
            partes = []
            for chunk in r.iter_content(8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DESCARGA_BYTES:
                    raise ValueError("La imagen excede el tamaño máximo permitido (15 MB).")
                partes.append(chunk)
            contenido = b"".join(partes)
            if not contenido:
                raise ValueError("La URL no devolvió contenido.")
            return contenido
        finally:
            r.close()
    raise ValueError("Demasiadas redirecciones.")
