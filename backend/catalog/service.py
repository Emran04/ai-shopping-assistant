import re
from datetime import UTC, datetime
from pathlib import Path

from models import (
    MAX_PRICE_MINOR,
    Category,
    Product,
    ProductCategory,
    ProductImage,
    ProductVariant,
)
from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import delete, exists
from sqlmodel import Session, select

CATEGORY_KINDS = ("audience", "clothing_type")
SLUG_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"


class CatalogError(ValueError):
    pass


class StorageCredentials(BaseModel):
    model_config = {"hide_input_in_errors": True}

    access_key_id: SecretStr = Field(min_length=1)
    secret_access_key: SecretStr = Field(min_length=1)


class CatalogSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_prefix="CATALOG_", env_ignore_empty=True, extra="ignore", hide_input_in_errors=True,
    )

    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    default_storage_id: str | None = None
    storage_credentials: dict[str, StorageCredentials] = Field(default_factory=dict)
    image_cdn_url: str | None = Field(default=None, validation_alias="IMAGE_CDN_URL")

    @field_validator("image_cdn_url")
    @classmethod
    def normalize_image_cdn_url(cls, value: str | None) -> str | None:
        if value is None or not (base := value.strip()):
            return None
        url = HttpUrl(base if "://" in base else f"https://{base}")
        if url.query is not None or url.fragment is not None:
            raise ValueError("Use an image CDN base URL without a query or fragment.")
        return str(url).rstrip("/")


def label(value: str, max_length: int, field: str) -> str:
    value = value.strip()
    if not value or len(value) > max_length or "\x00" in value:
        raise CatalogError(f"{field} must contain 1 to {max_length} characters.")
    return value


def slug_value(value: str) -> str:
    if len(value) > 120 or not re.fullmatch(SLUG_PATTERN, value):
        raise CatalogError("Use a lowercase slug with letters, digits, and single hyphens.")
    return value


def variant_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def lock_product(session: Session, product_id: int) -> Product:
    product = session.exec(
        select(Product).where(Product.id == product_id).with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if product is None:
        raise CatalogError("Product does not exist.")
    return product


def validate_publication(session: Session, product: Product, store_currency: str | None) -> None:
    if product.status != "active":
        return
    if not store_currency or product.currency != store_currency or product.price_minor is None:
        raise CatalogError("Enter a price in the configured store currency before publishing.")
    audience = exists().where(
        ProductCategory.product_id == product.id,
        ProductCategory.category_id == Category.id,
        Category.kind == "audience",
    )
    enabled_variant = exists().where(ProductVariant.product_id == product.id, ProductVariant.enabled)
    ready_image = exists().where(ProductImage.product_id == product.id, ProductImage.state == "ready")
    has_audience, has_variant, has_image = session.exec(
        select(audience, enabled_variant, ready_image)
    ).one()
    missing = [
        name for present, name in ((has_audience, "an audience category"),
                                   (has_variant, "an enabled variant"), (has_image, "a ready image"))
        if not present
    ]
    if missing:
        raise CatalogError(f"An active product requires {', '.join(missing)}.")


def set_price(product: Product, price_minor: int, currency: str | None) -> None:
    if not currency:
        raise CatalogError("Configure CATALOG_CURRENCY before entering prices.")
    if not 0 <= price_minor <= MAX_PRICE_MINOR:
        raise CatalogError(f"Price must be between 0 and {MAX_PRICE_MINOR} minor units.")
    product.price_minor = price_minor
    product.currency = currency


def set_status(session: Session, product: Product, status: str, currency: str | None) -> None:
    product.status = status
    if status == "active" and product.first_published_at is None:
        product.first_published_at = datetime.now(UTC)
    validate_publication(session, product, currency)


def upsert_category(session: Session, kind: str, slug: str, name: str, order: int) -> Category:
    slug_value(slug)
    name = label(name, 120, "Category name")
    if kind not in CATEGORY_KINDS or not 0 <= order <= 2_147_483_647:
        raise CatalogError("Use a supported category kind and a nonnegative display order.")
    category = session.exec(select(Category).where(Category.kind == kind, Category.slug == slug)).one_or_none()
    if category is None:
        category = Category(kind=kind, slug=slug)
    category.name = name
    category.sort_order = order
    session.add(category)
    return category


def set_categories(
    session: Session, product: Product, category_keys: list[str], currency: str | None,
) -> None:
    category_ids = set()
    for key in category_keys:
        kind, separator, slug = key.partition(":")
        if not separator or kind not in CATEGORY_KINDS:
            raise CatalogError("Give each category as audience:men or clothing_type:t-shirts.")
        category_id = session.exec(
            select(Category.id).where(Category.kind == kind, Category.slug == slug)
        ).one_or_none()
        if category_id is None:
            raise CatalogError(f"Unknown category {key!r}.")
        category_ids.add(category_id)
    session.exec(delete(ProductCategory).where(ProductCategory.product_id == product.id))
    session.add_all(
        ProductCategory(product_id=product.id, category_id=category_id) for category_id in category_ids
    )
    validate_publication(session, product, currency)


def upsert_variant(
    session: Session, product: Product, sku: str, size: str, color: str,
    stock: int, enabled: bool, currency: str | None,
) -> ProductVariant:
    sku = label(sku, 80, "SKU")
    size = label(size, 80, "Size")
    color = label(color, 80, "Color")
    size_key, color_key = variant_key(size), variant_key(color)
    if max(len(size_key), len(color_key)) > 160:
        raise CatalogError("Normalized sizes and colors must fit within 160 characters.")
    if not 0 <= stock <= 2_147_483_647:
        raise CatalogError("Stock must be between 0 and 2147483647.")
    variant = session.exec(select(ProductVariant).where(ProductVariant.sku == sku)).one_or_none()
    if variant is None:
        variant = ProductVariant(product_id=product.id, sku=sku)
    elif variant.product_id != product.id:
        raise CatalogError("This SKU belongs to another product.")
    variant.size, variant.color = size, color
    variant.size_key, variant.color_key = size_key, color_key
    variant.stock_quantity, variant.enabled = stock, enabled
    session.add(variant)
    validate_publication(session, product, currency)
    return variant
