"""Almacenamiento de imágenes.

Por defecto guarda en el disco local del contenedor (cero configuración) y las
sirve en `/fotos/...`. Si se configuran las claves de Spaces, usa DigitalOcean
Spaces (S3) y devuelve la URL pública.
"""

import os

from app.config import get_settings


def _client():
    # Import lazy: boto3 y botocore solo se importan cuando realmente se usan
    # (cuando el deploy configura Spaces). Asi, tests y dev local no necesitan
    # instalar boto3 solo para importar este módulo.
    import boto3
    from botocore.client import Config

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
            Bucket=s.spaces_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ACL="public-read",
        )
        return f"{s.public_base_url}/{key}"

    # Almacenamiento local (por defecto)
    path = os.path.join(s.local_storage_dir, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return f"/fotos/{key}"


def upload_file(data: bytes, key: str, content_type: str) -> str:
    """Guarda un archivo (foto o video) y devuelve su URL (Spaces o local /fotos/...)."""
    s = get_settings()
    if s.usa_spaces:
        _client().put_object(
            Bucket=s.spaces_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ACL="public-read",
        )
        return f"{s.public_base_url}/{key}"

    path = os.path.join(s.local_storage_dir, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return f"/fotos/{key}"


def delete_file(key: str) -> None:
    s = get_settings()
    if s.usa_spaces:
        _client().delete_object(Bucket=s.spaces_bucket, Key=key)
    else:
        try:
            os.remove(os.path.join(s.local_storage_dir, key))
        except FileNotFoundError:
            pass


def delete_image(key: str) -> None:
    s = get_settings()
    if s.usa_spaces:
        _client().delete_object(Bucket=s.spaces_bucket, Key=key)
    else:
        try:
            os.remove(os.path.join(s.local_storage_dir, key))
        except FileNotFoundError:
            pass
