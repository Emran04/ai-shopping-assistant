from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Text, UniqueConstraint, func, text
from sqlmodel import Field, SQLModel


MAX_PRICE_MINOR = 999_999_999_999
MAX_PRODUCT_TITLE_LENGTH = 255


class Product(SQLModel, table=True):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_product_status"),
        CheckConstraint(
            "(price_minor IS NULL AND currency IS NULL) OR "
            f"(price_minor IS NOT NULL AND price_minor BETWEEN 0 AND {MAX_PRICE_MINOR} "
            "AND currency IS NOT NULL AND currency ~ '^[A-Z]{3}$')",
            name="ck_product_price",
        ),
        CheckConstraint(
            "status <> 'active' OR (price_minor IS NOT NULL AND first_published_at IS NOT NULL)",
            name="ck_product_publish",
        ),
        UniqueConstraint("slug", name="uq_products_slug"),
        UniqueConstraint("demo_seed_key", name="uq_products_demo_seed_key"),
        Index("ix_products_status_price_id", "status", "price_minor", "id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1, max_length=MAX_PRODUCT_TITLE_LENGTH)
    slug: str = Field(max_length=120)
    demo_seed_key: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, sa_type=Text)
    price_minor: int | None = Field(default=None, sa_type=BigInteger)
    currency: str | None = Field(default=None, max_length=3)
    status: str = Field(default="draft", max_length=12, sa_column_kwargs={"server_default": "draft"})
    first_published_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=False,
        sa_column_kwargs={"server_default": func.now()},
    )
    updated_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=False,
        sa_column_kwargs={"server_default": func.now(), "onupdate": lambda: datetime.now(UTC)},
    )


class Category(SQLModel, table=True):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("kind IN ('audience', 'clothing_type')", name="ck_category_kind"),
        CheckConstraint("sort_order >= 0", name="ck_category_order"),
        UniqueConstraint("kind", "slug", name="uq_category_kind_slug"),
    )

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(max_length=20)
    name: str = Field(max_length=120)
    slug: str = Field(max_length=120)
    sort_order: int = Field(default=0, sa_column_kwargs={"server_default": "0"})


class ProductCategory(SQLModel, table=True):
    __tablename__ = "product_categories"
    __table_args__ = (Index("ix_product_categories_category_product", "category_id", "product_id"),)

    product_id: int = Field(primary_key=True, foreign_key="products.id", ondelete="CASCADE")
    category_id: int = Field(primary_key=True, foreign_key="categories.id", ondelete="RESTRICT")


class ProductVariant(SQLModel, table=True):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="ck_variant_stock"),
        UniqueConstraint("product_id", "size_key", "color_key", name="uq_variant_size_color"),
    )

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.id", ondelete="CASCADE")
    sku: str = Field(max_length=80, unique=True)
    size: str = Field(max_length=80)
    color: str = Field(max_length=80)
    size_key: str = Field(max_length=160)
    color_key: str = Field(max_length=160)
    stock_quantity: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    enabled: bool = Field(default=True, sa_column_kwargs={"server_default": text("true")})


class MediaStorageLocation(SQLModel, table=True):
    __tablename__ = "media_storage_locations"
    __table_args__ = (
        CheckConstraint("provider = 'r2'", name="ck_media_storage_provider"),
        UniqueConstraint("endpoint_url", "bucket_name", name="uq_media_storage_bucket"),
    )

    storage_id: str = Field(primary_key=True, max_length=80)
    provider: str = Field(default="r2", max_length=20, sa_column_kwargs={"server_default": "r2"})
    bucket_name: str = Field(max_length=63)
    endpoint_url: str = Field(max_length=255)


class ProductImage(SQLModel, table=True):
    __tablename__ = "product_images"
    __table_args__ = (
        CheckConstraint("state IN ('pending', 'ready', 'deleting', 'deleted')", name="ck_image_state"),
        CheckConstraint("sort_order >= 0", name="ck_image_order"),
        Index("ix_product_images_gallery", "product_id", "state", "sort_order", "id"),
        Index("ix_product_images_cleanup", "state", "updated_at"),
    )

    id: UUID = Field(primary_key=True)
    product_id: int = Field(foreign_key="products.id", ondelete="RESTRICT")
    storage_id: str = Field(max_length=80, foreign_key="media_storage_locations.storage_id", ondelete="RESTRICT")
    original_key: str = Field(max_length=255)
    thumbnail_key: str = Field(max_length=255)
    alt_text: str = Field(max_length=250)
    sort_order: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    state: str = Field(default="pending", max_length=12, sa_column_kwargs={"server_default": "pending"})
    replaces_image_id: UUID | None = Field(default=None)
    created_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=False,
        sa_column_kwargs={"server_default": func.now()},
    )
    updated_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=False,
        sa_column_kwargs={"server_default": func.now(), "onupdate": lambda: datetime.now(UTC)},
    )


class MediaRetirement(SQLModel, table=True):
    __tablename__ = "media_retirements"

    image_id: UUID = Field(primary_key=True, foreign_key="product_images.id", ondelete="RESTRICT")
    storage_id: str = Field(
        primary_key=True, max_length=80, foreign_key="media_storage_locations.storage_id", ondelete="RESTRICT"
    )
    delete_after: datetime = Field(sa_type=DateTime(timezone=True), index=True)
