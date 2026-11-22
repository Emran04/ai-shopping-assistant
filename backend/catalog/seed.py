import re
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from botocore.exceptions import ClientError
from models import (
    MAX_PRICE_MINOR,
    Category,
    MediaStorageLocation,
    Product,
    ProductCategory,
    ProductImage,
    ProductVariant,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine, text
from sqlmodel import Session, select

from .media import gallery
from .service import (
    CatalogError,
    CatalogSettings,
    label,
    set_categories,
    set_price,
    set_status,
    slug_value,
    upsert_category,
    upsert_variant,
    variant_key,
)
from .storage import (
    DEMO_IMAGE_PREFIX,
    MAX_IMAGE_BYTES,
    STORAGE_ID,
    R2Storage,
    object_error,
    storage_location,
)

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "data" / "demo-products.json"


class DemoVariant(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, strict=True)

    sku: str = Field(min_length=1, max_length=80)
    size: str = Field(min_length=1, max_length=80)
    color: str = Field(min_length=1, max_length=80)
    stock_quantity: int = Field(ge=0, le=2_147_483_647)


class DemoCover(BaseModel):
    path: str
    alt_text: str
    storage_id: str
    original_key: str
    thumbnail_key: str


class DemoProduct(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, strict=True)

    key: str
    name: str
    slug: str
    description: str
    audience: Literal["men", "women", "kids"]
    clothing_type: str
    price_minor: int = Field(ge=0, le=MAX_PRICE_MINOR)
    variants: list[DemoVariant] = Field(min_length=1)
    cover: DemoCover


class DemoManifest(BaseModel):
    schema_version: Literal[1]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    clothing_types: dict[str, str]
    products: list[DemoProduct] = Field(min_length=1)


def load_manifest(path: Path) -> DemoManifest:
    try:
        manifest = DemoManifest.model_validate_json(path.read_bytes())
    except ValidationError as exc:
        errors = ", ".join(".".join(map(str, item["loc"])) for item in exc.errors(include_input=False))
        raise CatalogError(f"Invalid demo manifest fields: {errors}.") from None

    directory = path.resolve().parent
    for slug, name in manifest.clothing_types.items():
        slug_value(slug)
        label(name, 120, "Clothing type")
    if (
        len({item.key for item in manifest.products}) != len(manifest.products)
        or len({item.slug for item in manifest.products}) != len(manifest.products)
    ):
        raise CatalogError("Demo product keys and slugs must be unique.")
    skus = [variant.sku for item in manifest.products for variant in item.variants]
    if len(set(skus)) != len(skus):
        raise CatalogError("Demo variant SKUs must be unique.")

    for item in manifest.products:
        slug_value(item.key)
        slug_value(item.slug)
        label(item.name, 255, "Demo product name")
        label(item.description, 8_000, "Demo product description")
        label(item.cover.alt_text, 250, "Demo cover alt text")
        if not item.key.startswith(f"demo-{item.audience}-") or item.clothing_type not in manifest.clothing_types:
            raise CatalogError(f"Invalid categories for {item.key}.")
        for variant in item.variants:
            label(variant.sku, 80, "Demo SKU")
            label(variant.size, 80, "Demo size")
            label(variant.color, 80, "Demo color")
        sizes = {(variant_key(variant.size), variant_key(variant.color)) for variant in item.variants}
        if len(sizes) != len(item.variants):
            raise CatalogError(f"Duplicate size and color for {item.key}.")
        if not re.fullmatch(STORAGE_ID, item.cover.storage_id):
            raise CatalogError(f"Invalid storage ID for {item.key}.")
        image = (directory / item.cover.path).resolve()
        if not image.is_relative_to(directory / "images" / "demo"):
            raise CatalogError(f"Cover path must be inside images/demo for {item.key}.")
        with image.open("rb") as source:
            content = source.read(MAX_IMAGE_BYTES + 1)
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise CatalogError(f"Invalid cover file size for {item.key}.")
        prefix = f"{DEMO_IMAGE_PREFIX}{item.key}/"
        expected_original = f"{prefix}original-{sha256(content).hexdigest()}.jpg"
        if item.cover.original_key != expected_original or not re.fullmatch(
            re.escape(prefix) + r"thumbnail-[0-9a-f]{64}\.webp", item.cover.thumbnail_key,
        ):
            raise CatalogError(f"Invalid R2 image paths or original checksum for {item.key}.")
    return manifest


def verify_covers(engine: Engine, storage: R2Storage, products: list[DemoProduct]) -> None:
    with Session(engine) as session:
        locations = {
            key: storage_location(session, key) for key in {item.cover.storage_id for item in products}
        }

    def verify(client, location: MediaStorageLocation, cover: DemoCover) -> None:
        for key, content_type in ((cover.original_key, "image/jpeg"), (cover.thumbnail_key, "image/webp")):
            digest = Path(key).stem.rsplit("-", 1)[1]
            try:
                metadata = client.head_object(Bucket=location.bucket_name, Key=key)
            except ClientError as exc:
                raise CatalogError(f"Cannot verify R2 object {key}: {object_error(exc)}.") from None
            if metadata.get("ContentType") != content_type or metadata.get("Metadata", {}).get("sha256") != digest:
                raise CatalogError(f"R2 object metadata does not match the manifest for {key}.")

    for storage_id, location in locations.items():
        with storage.open(location) as client, ThreadPoolExecutor(max_workers=8) as executor:
            requests = (
                executor.submit(verify, client, location, item.cover)
                for item in products if item.cover.storage_id == storage_id
            )
            futures = list(requests)
            for future in futures:
                future.result()


def sync_product(session: Session, item: DemoProduct, currency: str, dry_run: bool) -> str:
    statement = select(Product).where(Product.demo_seed_key == item.key)
    product = session.exec(statement if dry_run else statement.with_for_update()).one_or_none()
    is_new = product is None
    if is_new or product.first_published_at is None:
        owner = session.exec(select(Product.id).where(Product.slug == item.slug)).one_or_none()
        if owner is not None and (is_new or owner != product.id):
            raise CatalogError(f"Slug already belongs to another product: {item.slug}.")

    sku_rows = session.exec(
        select(ProductVariant).where(ProductVariant.sku.in_([variant.sku for variant in item.variants]))
    ).all()
    if any(is_new or variant.product_id != product.id for variant in sku_rows):
        raise CatalogError(f"A variant SKU for {item.key} already belongs to another product.")
    variants = {variant.sku: variant for variant in sku_rows}
    stale_variants = [
        wanted for wanted in item.variants if (row := variants.get(wanted.sku)) is None
        or (row.size, row.color, row.stock_quantity, row.enabled)
        != (wanted.size, wanted.color, wanted.stock_quantity, True)
    ]

    categories = {("audience", item.audience), ("clothing_type", item.clothing_type)}
    current_categories = set() if is_new else set(session.exec(
        select(Category.kind, Category.slug).join(ProductCategory)
        .where(ProductCategory.product_id == product.id)
    ).all())
    images = [] if is_new else gallery(session, product.id)
    cover = item.cover
    current_image = next((row for row in images if (
        row.storage_id, row.original_key, row.thumbnail_key
    ) == (cover.storage_id, cover.original_key, cover.thumbnail_key)), None)
    other_demo_images = [
        row for row in images if row is not current_image
        and row.original_key.startswith(f"{DEMO_IMAGE_PREFIX}{item.key}/")
    ]
    cover_changed = current_image is None or images[0] is not current_image or (
        current_image.alt_text != cover.alt_text
    ) or bool(other_demo_images)
    product_changed = is_new or (
        product.name, product.description, product.price_minor, product.currency, product.status
    ) != (item.name, item.description, item.price_minor, currency, "active") or (
        product.first_published_at is None and product.slug != item.slug
    )
    changed = product_changed or cover_changed or current_categories != categories or bool(stale_variants)
    result = "created" if is_new else ("updated" if changed else "unchanged")
    if dry_run or not changed:
        return result

    if is_new:
        product = Product(name=item.name, slug=item.slug, demo_seed_key=item.key)
        session.add(product)
    elif product.first_published_at is None:
        product.slug = item.slug
    product.name, product.description = item.name, item.description
    set_price(product, item.price_minor, currency)
    session.flush()

    if cover_changed:
        if current_image is None:
            current_image = ProductImage(
                id=uuid4(), product_id=product.id, storage_id=cover.storage_id,
                original_key=cover.original_key, thumbnail_key=cover.thumbnail_key,
                alt_text=cover.alt_text, state="ready",
            )
            session.add(current_image)
        current_image.alt_text = cover.alt_text
        current_image.sort_order = 0
        for image in other_demo_images:
            image.state = "deleted"
        other_images = (row for row in images if row is not current_image and row.state == "ready")
        for order, image in enumerate(other_images, 1):
            image.sort_order = order
    if current_categories != categories:
        set_categories(session, product, [f"{kind}:{slug}" for kind, slug in sorted(categories)], currency)
    for variant in stale_variants:
        upsert_variant(
            session, product, variant.sku, variant.size, variant.color, variant.stock_quantity, True, currency,
        )
    set_status(session, product, "active", currency)
    return result


def seed_demo(
    engine: Engine, storage: R2Storage, settings: CatalogSettings, path: Path, *, dry_run: bool = False,
) -> dict:
    manifest = load_manifest(path)
    if settings.currency != manifest.currency:
        raise CatalogError(f"Set CATALOG_CURRENCY to {manifest.currency} for this demo manifest.")
    verify_covers(engine, storage, manifest.products)
    summary = {"created": 0, "updated": 0, "unchanged": 0}
    with Session(engine) as session, session.begin():
        if not dry_run:
            session.execute(text("SELECT pg_advisory_xact_lock(hashtext('catalog.seed-demo'))"))
            catalog_types = set(session.exec(select(Category.slug).where(Category.kind == "clothing_type")))
            for order, (slug, name) in enumerate(manifest.clothing_types.items()):
                if slug not in catalog_types:
                    upsert_category(session, "clothing_type", slug, name, order)
        for product in manifest.products:
            summary[sync_product(session, product, manifest.currency, dry_run)] += 1
    return {"dry_run": dry_run, **summary}
