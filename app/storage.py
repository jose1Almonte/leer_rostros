"""Almacenamiento de imágenes.

Por defecto guarda en el disco local del contenedor (cero configuración) y las
sirve en `/fotos/...`. Si se configuran las claves de Spaces, usa DigitalOcean
Spaces (S3) y devuelve la URL pública.
"""

import os

import boto3
from botocore.client import Config

from app.config import get_settings


def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        region_name=s.spaces_region,
        endpoint_url=s.endpoint_url,
        aws_access_key_id=s.spaces_key,
        aws_secret_access_key=s.spaces_secret,
        config=Config(s3={"addressing_style": "virtual"}),
    )


def upload_image(data: bytes, key: str, content_type: str = "image/jpeg") -> str:
    """Guarda la imagen y devuelve su URL (Spaces o local /fotos/...)."""
    s = get_settings()
    if s.usa_spaces:
        _client().put_object(
            Bucket=s.spaces_bucket, Key=key, Body=data,
            ContentType=content_type, ACL="public-read",
        )
        return f"{s.public_base_url}/{key}"

    # Almacenamiento local (por defecto)
    path = os.path.join(s.local_storage_dir, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return f"/fotos/{key}"


def delete_image(key: str) -> None:
    s = get_settings()
    if s.usa_spaces:
        _client().delete_object(Bucket=s.spaces_bucket, Key=key)
    else:
        try:
            os.remove(os.path.join(s.local_storage_dir, key))
        except FileNotFoundError:
            pass
