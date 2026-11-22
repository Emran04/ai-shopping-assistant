import logging
import re
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import BinaryIO
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from models import MediaRetirement, MediaStorageLocation, ProductImage
from sqlalchemy import Engine, func, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from .service import (
    CatalogError,
    CatalogSettings,
    label,
    lock_product,
    validate_publication,
)
from .storage import (
    MAX_IMAGE_BYTES,
    ObjectMissing,
    R2Storage,
    delete_object,
    get_object,
    prepare_image,
    put_image_object,
    storage_location,
)

logger = logging.getLogger(__name__)
GRACE_PERIOD = timedelta(hours=24)
STORAGE_FAILURES = (BotoCoreError, ClientError, CatalogError)


@contextmanager
def image_session(engine: Engine, image_id: UUID) -> Iterator[Session]:
    lock_key = int.from_bytes(sha256(b"catalog-image:" + image_id.bytes).digest()[:8], signed=True)
    parameters = {"key": lock_key}
    with engine.connect() as connection:
        try:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), parameters)
            connection.commit()
            with Session(bind=connection, expire_on_commit=False) as session:
                yield session
        finally:
            connection.rollback()
            if not connection.invalidated:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), parameters)
                    connection.commit()
                except SQLAlchemyError:
                    connection.invalidate()
                    raise


def gallery(session: Session, product_id: int) -> list[ProductImage]:
    return list(session.exec(
        select(ProductImage).where(ProductImage.product_id == product_id, ProductImage.state == "ready")
        .order_by(ProductImage.sort_order, ProductImage.id)
    ))


def ready_image(session: Session, image_id: UUID, product_id: int | None = None) -> ProductImage:
    image = session.get(ProductImage, image_id, populate_existing=True)
    if image is None or image.state != "ready" or (product_id is not None and image.product_id != product_id):
        raise CatalogError("Ready image does not exist.")
    return image


def upload_image(
    engine: Engine, storage: R2Storage, settings: CatalogSettings, product_id: int, image_id: UUID,
    source: BinaryIO, alt_text: str, *, storage_id: str | None = None, replace: UUID | None = None,
) -> ProductImage:
    alt_text = label(alt_text, 250, "Alt text")
    prepared = prepare_image(source)
    prefix = f"products/{product_id}/{image_id}"
    original_key = f"{prefix}/original-{prepared.digest}.{prepared.extension}"
    thumbnail_key = f"{prefix}/thumbnail.webp"
    with image_session(engine, image_id) as session:
        with session.begin():
            lock_product(session, product_id)
            image = session.get(ProductImage, image_id)
            if image is not None:
                if (image.product_id, image.original_key, image.replaces_image_id) != (product_id, original_key, replace):
                    raise CatalogError("This upload ID already belongs to a different upload.")
                if image.state == "ready":
                    return image
                if image.state != "pending":
                    raise CatalogError("This upload was retired. Start again with a new upload ID.")
                image.alt_text = alt_text
                image.updated_at = datetime.now(UTC)
                location = storage_location(session, image.storage_id)
            else:
                if replace is not None:
                    ready_image(session, replace, product_id)
                location = storage_location(session, storage_id or settings.default_storage_id)
                image = ProductImage(
                    id=image_id, product_id=product_id, storage_id=location.storage_id,
                    original_key=original_key, thumbnail_key=thumbnail_key, alt_text=alt_text,
                    replaces_image_id=replace,
                )
                session.add(image)
        try:
            with storage.open(location) as client:
                put_image_object(client, location.bucket_name, original_key, prepared.original, prepared.content_type)
                put_image_object(client, location.bucket_name, thumbnail_key, prepared.thumbnail, "image/webp")
        except STORAGE_FAILURES as exc:
            logger.warning("Catalog upload pending image=%s storage=%s error=%s",
                           image_id, location.storage_id, type(exc).__name__)
            raise
        with session.begin():
            lock_product(session, product_id)
            if replace is not None:
                previous = ready_image(session, replace, product_id)
                image.sort_order = previous.sort_order
                previous.state = "deleting"
            else:
                last = session.exec(select(func.max(ProductImage.sort_order)).where(
                    ProductImage.product_id == product_id, ProductImage.state == "ready"
                )).one()
                image.sort_order = 0 if last is None else last + 1
            image.state = "ready"
        return image


def reorder_images(session: Session, product_id: int, ordered_ids: list[UUID]) -> None:
    lock_product(session, product_id)
    images = {image.id: image for image in gallery(session, product_id)}
    if set(ordered_ids) != set(images) or len(ordered_ids) != len(images):
        raise CatalogError("List each ready image ID once in the new gallery order.")
    for position, image_id in enumerate(ordered_ids):
        images[image_id].sort_order = position


def remove_image(engine: Engine, image_id: UUID, currency: str | None) -> None:
    with image_session(engine, image_id) as session, session.begin():
        image = ready_image(session, image_id)
        product = lock_product(session, image.product_id)
        image = ready_image(session, image_id, product.id)
        image.state = "deleting"
        validate_publication(session, product, currency)


def download_original(engine: Engine, storage: R2Storage, image_id: UUID, output: BinaryIO) -> None:
    with image_session(engine, image_id) as session:
        with session.begin():
            image = ready_image(session, image_id)
            location = storage_location(session, image.storage_id)
        with storage.open(location) as client:
            result = get_object(client, location.bucket_name, image.original_key)
            with closing(result["Body"]) as body:
                for chunk in body.iter_chunks(64 * 1024):
                    output.write(chunk)


def move_image(engine: Engine, storage: R2Storage, image_id: UUID, target_id: str) -> None:
    with image_session(engine, image_id) as session:
        with session.begin():
            image = ready_image(session, image_id)
            source = storage_location(session, image.storage_id)
            target = storage_location(session, target_id)
        if source.storage_id == target_id:
            return
        with storage.open(source) as reader, storage.open(target) as writer:
            for key in (image.original_key, image.thumbnail_key):
                result = get_object(reader, source.bucket_name, key)
                with closing(result["Body"]) as body:
                    content = body.read(MAX_IMAGE_BYTES + 1)
                if (len(content) > MAX_IMAGE_BYTES or
                        sha256(content).hexdigest() != result.get("Metadata", {}).get("sha256")):
                    raise CatalogError("Source object failed checksum validation.")
                put_image_object(writer, target.bucket_name, key, content, result["ContentType"])
                copied = get_object(writer, target.bucket_name, key)
                with closing(copied["Body"]) as body:
                    verified = body.read(MAX_IMAGE_BYTES + 1)
                if content != verified:
                    raise CatalogError("Copied object failed verification.")
        with session.begin():
            lock_product(session, image.product_id)
            image = ready_image(session, image_id)
            retirement = session.get(MediaRetirement, (image_id, target_id))
            if retirement:
                session.delete(retirement)
            session.add(MediaRetirement(
                image_id=image_id, storage_id=source.storage_id, delete_after=datetime.now(UTC) + GRACE_PERIOD,
            ))
            image.storage_id = target_id


def delete_objects(storage: R2Storage, location: MediaStorageLocation, image: ProductImage) -> None:
    with storage.open(location) as client:
        for key in (image.original_key, image.thumbnail_key):
            delete_object(client, location.bucket_name, key)


def clean_catalog(engine: Engine, storage: R2Storage) -> dict:
    now = datetime.now(UTC)
    cutoff = now - GRACE_PERIOD
    with Session(engine) as session:
        image_ids = session.exec(select(ProductImage.id).where(or_(
            ProductImage.state == "deleting", # type: ignore
            (ProductImage.state == "pending") & (ProductImage.updated_at < cutoff), # type: ignore
        ))).all()
        retirements = session.exec(select(MediaRetirement.image_id, MediaRetirement.storage_id).where(
            MediaRetirement.delete_after <= now,
        )).all()
    result = {"images_deleted": 0, "copies_deleted": 0, "failures": 0}
    for image_id in image_ids:
        try:
            with image_session(engine, image_id) as session:
                with session.begin():
                    image = session.get(ProductImage, image_id)
                    if image.state == "pending" and image.updated_at < cutoff:
                        logger.info("Reclaiming pending catalog image=%s updated_at=%s", image.id, image.updated_at)
                        image.state = "deleting"
                    if image.state != "deleting":
                        continue
                    location = storage_location(session, image.storage_id)
                delete_objects(storage, location, image)
                with session.begin():
                    image.state = "deleted"
                result["images_deleted"] += 1
        except STORAGE_FAILURES as exc:
            logger.warning("Catalog image cleanup failed image=%s error=%s", image_id, type(exc).__name__)
            result["failures"] += 1
    for image_id, storage_id in retirements:
        try:
            with image_session(engine, image_id) as session:
                with session.begin():
                    retirement = session.get(MediaRetirement, (image_id, storage_id))
                    if not retirement or retirement.delete_after > now:
                        continue
                    image = session.get(ProductImage, image_id)
                    if image.storage_id == storage_id: # type: ignore
                        continue
                    location = storage_location(session, storage_id)
                delete_objects(storage, location, image)
                with session.begin():
                    session.delete(retirement)
                result["copies_deleted"] += 1
        except STORAGE_FAILURES as exc:
            logger.warning("Catalog copy cleanup failed image=%s storage=%s error=%s",
                           image_id, storage_id, type(exc).__name__)
            result["failures"] += 1
    return result


def reconcile_catalog(engine: Engine, storage: R2Storage, *, delete_orphans: bool = False) -> dict:
    cutoff = datetime.now(UTC) - GRACE_PERIOD
    with Session(engine, expire_on_commit=False) as session:
        locations = session.exec(select(MediaStorageLocation)).all()
        ready_ids = session.exec(select(ProductImage.id).where(ProductImage.state == "ready")).all()
    report = {"missing": [], "orphans": [], "orphans_deleted": 0, "failures": []}
    for image_id in ready_ids:
        try:
            with image_session(engine, image_id) as session:
                with session.begin():
                    image = session.get(ProductImage, image_id)
                    if image.state != "ready":
                        continue
                    location = storage_location(session, image.storage_id)
                with storage.open(location) as client:
                    for key in (image.original_key, image.thumbnail_key):
                        try:
                            response = get_object(client, location.bucket_name, key)
                        except ObjectMissing:
                            report["missing"].append({"storage_id": location.storage_id, "key": key})
                        else:
                            response["Body"].close()
        except STORAGE_FAILURES as exc:
            report["failures"].append({"image_id": str(image_id), "error": type(exc).__name__})
    for location in locations:
        try:
            with storage.open(location) as client:
                for page in client.get_paginator("list_objects_v2").paginate(
                    Bucket=location.bucket_name, Prefix="products/",
                ):
                    for item in page.get("Contents", []):
                        if item["LastModified"] >= cutoff:
                            continue
                        key = item["Key"]
                        parts = key.split("/")
                        if len(parts) != 4 or not parts[1].isdigit():
                            continue
                        if parts[3] != "thumbnail.webp" and not re.fullmatch(
                            r"original-[0-9a-f]{64}\.(?:jpg|png|webp)", parts[3],
                        ):
                            continue
                        try:
                            image_id = UUID(parts[2])
                        except ValueError:
                            continue
                        if str(image_id) != parts[2]:
                            continue
                        with image_session(engine, image_id) as session:
                            with session.begin():
                                image = session.get(ProductImage, image_id)
                                is_known_key = image is not None and key in (image.original_key, image.thumbnail_key)
                                if is_known_key and (
                                    (image.storage_id == location.storage_id and image.state != "deleted")
                                    or session.get(MediaRetirement, (image_id, location.storage_id))
                                ):
                                    continue
                            report["orphans"].append({"storage_id": location.storage_id, "key": key})
                            if delete_orphans:
                                delete_object(client, location.bucket_name, key)
                                report["orphans_deleted"] += 1
        except STORAGE_FAILURES as exc:
            report["failures"].append({"storage_id": location.storage_id, "error": type(exc).__name__})
    return report
