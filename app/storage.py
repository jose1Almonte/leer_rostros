"""Subida de imágenes a DigitalOcean Spaces (almacenamiento compatible con S3)."""

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
    """Sube los bytes al Space con acceso público de lectura y devuelve su URL."""
    s = get_settings()
    _client().put_object(
        Bucket=s.spaces_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        ACL="public-read",
    )
    return f"{s.public_base_url}/{key}"


def delete_image(key: str) -> None:
    s = get_settings()
    _client().delete_object(Bucket=s.spaces_bucket, Key=key)
