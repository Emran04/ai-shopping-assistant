import re
from contextlib import closing
from hashlib import sha256
from io import BytesIO
from typing import BinaryIO, NamedTuple

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from models import MediaStorageLocation
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlmodel import Session

from .service import CatalogError, CatalogSettings

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
DEMO_IMAGE_PREFIX = "demo-products/"
IMAGE_FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}
R2_ENDPOINT = r"https://[a-f0-9]{32}(?:\.(?:eu|us|fedramp))?\.r2\.cloudflarestorage\.com"
STORAGE_ID = r"[a-z0-9][a-z0-9-]{0,79}"
BUCKET_NAME = r"[a-z0-9](?:[a-z0-9-]{1,61})[a-z0-9]"


class ObjectMissing(CatalogError):
    pass


class PreparedImage(NamedTuple):
    original: bytes
    thumbnail: bytes
    extension: str
    content_type: str
    digest: str


def prepare_image(source: BinaryIO) -> PreparedImage:
    original = source.read(MAX_IMAGE_BYTES + 1)
    if not original or len(original) > MAX_IMAGE_BYTES:
        raise CatalogError("Image must be between 1 byte and 10 MiB.")
    try:
        with Image.open(BytesIO(original), formats=tuple(IMAGE_FORMATS)) as image:
            extension, content_type = IMAGE_FORMATS[image.format]
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise CatalogError("Image must have at most 24 megapixels.")
            if getattr(image, "is_animated", False):
                raise CatalogError("Use a single-frame image.")
            image.verify()
        with Image.open(BytesIO(original), formats=tuple(IMAGE_FORMATS)) as image:
            oriented = ImageOps.exif_transpose(image)
            has_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
            thumbnail = oriented.convert("RGBA" if has_alpha else "RGB")
            thumbnail.thumbnail((768, 768), Image.Resampling.LANCZOS)
            thumbnail.info.clear()
            output = BytesIO()
            thumbnail.save(output, format="WEBP", quality=82, method=4)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        if isinstance(exc, CatalogError):
            raise
        raise CatalogError("Use a valid single-frame JPEG, PNG, or WebP image.") from exc
    return PreparedImage(original, output.getvalue(), extension, content_type, sha256(original).hexdigest())


def register_location(session: Session, storage_id: str, bucket: str, endpoint: str) -> MediaStorageLocation:
    endpoint = endpoint.removesuffix("/")
    if not re.fullmatch(STORAGE_ID, storage_id):
        raise CatalogError("Use a lowercase storage ID with letters, digits, and hyphens.")
    if not re.fullmatch(R2_ENDPOINT, endpoint) or not re.fullmatch(BUCKET_NAME, bucket):
        raise CatalogError("Enter a valid Cloudflare R2 API endpoint and bucket name.")
    location = session.get(MediaStorageLocation, storage_id)
    if location is not None:
        if (location.bucket_name, location.endpoint_url) != (bucket, endpoint):
            raise CatalogError("Register a different storage ID for a different bucket.")
        return location
    location = MediaStorageLocation(storage_id=storage_id, bucket_name=bucket, endpoint_url=endpoint)
    session.add(location)
    return location


def storage_location(session: Session, storage_id: str | None) -> MediaStorageLocation:
    location = session.get(MediaStorageLocation, storage_id) if storage_id else None
    if location is None:
        raise CatalogError("Register and select a catalog storage location.")
    return location


class R2Storage:
    def __init__(self, settings: CatalogSettings):
        self.credentials = settings.storage_credentials

    def open(self, location: MediaStorageLocation):
        credentials = self.credentials.get(location.storage_id)
        if credentials is None or not re.fullmatch(R2_ENDPOINT, location.endpoint_url):
            raise CatalogError(f"Storage location {location.storage_id} is missing valid R2 configuration.")
        return closing(boto3.session.Session().client(
            "s3",
            endpoint_url=location.endpoint_url,
            region_name="auto",
            aws_access_key_id=credentials.access_key_id.get_secret_value(),
            aws_secret_access_key=credentials.secret_access_key.get_secret_value(),
            config=Config(
                connect_timeout=3, read_timeout=10, retries={"mode": "standard", "total_max_attempts": 3},
                request_checksum_calculation="when_required", response_checksum_validation="when_required",
                s3={"addressing_style": "path"},
            ),
        ))


def object_error(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


def get_object(client, bucket: str, key: str) -> dict:
    try:
        return client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if object_error(exc) in {"404", "NoSuchKey", "NotFound"}:
            raise ObjectMissing("Image object is missing.") from exc
        raise


def delete_object(client, bucket: str, key: str) -> None:
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if object_error(exc) not in {"404", "NoSuchKey", "NotFound"}:
            raise


def put_image_object(client, bucket: str, key: str, data: bytes, content_type: str) -> None:
    checksum = sha256(data).hexdigest()
    try:
        client.put_object(
            Bucket=bucket, Key=key, Body=data, ContentType=content_type,
            Metadata={"sha256": checksum}, IfNoneMatch="*",
        )
    except ClientError as exc:
        if object_error(exc) not in {"412", "PreconditionFailed"}:
            raise
        metadata = client.head_object(Bucket=bucket, Key=key)
        if (metadata["ContentLength"], metadata.get("Metadata", {}).get("sha256")) != (len(data), checksum):
            raise CatalogError("An existing image object differs from the expected upload.") from exc
