from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from models import (
    MAX_PRICE_MINOR,
    MAX_PRODUCT_TITLE_LENGTH,
    Category,
    Product,
    ProductCategory,
    ProductImage,
    ProductVariant,
)
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_
from sqlmodel import Session, select

from .media import gallery
from .service import CatalogError, variant_key

FilterValue = Annotated[str, Field(min_length=1, max_length=120)]


class ProductFilters(BaseModel):
    audience: list[FilterValue] = Field(default_factory=list, max_length=20)
    clothing_type: list[FilterValue] = Field(default_factory=list, max_length=20)
    size: list[FilterValue] = Field(default_factory=list, max_length=20)
    color: list[FilterValue] = Field(default_factory=list, max_length=20)
    min_price: int | None = Field(default=None, ge=0, le=MAX_PRICE_MINOR, description="Price in minor units")
    max_price: int | None = Field(default=None, ge=0, le=MAX_PRICE_MINOR, description="Price in minor units")
    in_stock: bool = False
    q: str | None = Field(default=None, max_length=MAX_PRODUCT_TITLE_LENGTH, description="Product title or keywords")
    title: str | None = Field(default=None, max_length=MAX_PRODUCT_TITLE_LENGTH, description="Words in the product title")
    sort: Literal["newest", "name", "price_asc", "price_desc"] = "newest"
    page: int = Field(default=1, ge=1, le=100_000)
    page_size: int = Field(default=12, ge=1, le=48)


class CategorySummary(BaseModel):
    name: str
    slug: str


class Categories(BaseModel):
    audience: list[CategorySummary] = Field(default_factory=list)
    clothing_type: list[CategorySummary] = Field(default_factory=list)


class CatalogIndex(Categories):
    currency: str | None


class Thumbnail(BaseModel):
    id: UUID
    url: str
    alt_text: str


class ProductSummary(BaseModel):
    id: int
    slug: str
    name: str
    price_minor: int
    currency: str
    in_stock: bool
    cover: Thumbnail | None


class VariantSummary(BaseModel):
    sku: str
    size: str
    color: str
    in_stock: bool


class ProductDetail(ProductSummary):
    description: str | None
    categories: Categories
    variants: list[VariantSummary]
    images: list[Thumbnail]


class Facet(BaseModel):
    value: str
    label: str


class ProductPage(BaseModel):
    items: list[ProductSummary]
    page: int
    page_size: int
    total: int
    currency: str | None
    sizes: list[Facet] = Field(default_factory=list)
    colors: list[Facet] = Field(default_factory=list)


def catalog_categories(session: Session, product_id: int | None = None) -> Categories:
    statement = select(Category).order_by(Category.kind, Category.sort_order, Category.id)
    if product_id is not None:
        statement = statement.join(ProductCategory).where(ProductCategory.product_id == product_id)
    result = Categories()
    for category in session.exec(statement):
        getattr(result, category.kind).append(CategorySummary(name=category.name, slug=category.slug))
    return result


def thumbnail(image: ProductImage | None, image_cdn_url: str | None) -> Thumbnail | None:
    if image is None:
        return None
    if image_cdn_url:
        url = f"{image_cdn_url}/{quote(image.thumbnail_key)}"
    else:
        url = f"/catalog/media/{image.product_id}/{image.id}/thumbnail"
    return Thumbnail(id=image.id, url=url, alt_text=image.alt_text)


def summarize(
    product: Product, available: bool, image: ProductImage | None, image_cdn_url: str | None,
) -> ProductSummary:
    return ProductSummary(
        id=product.id, slug=product.slug, name=product.name, price_minor=product.price_minor,
        currency=product.currency, in_stock=available, cover=thumbnail(image, image_cdn_url),
    )


def filter_facets(session: Session, value, name) -> list[Facet]:
    rows = session.exec(
        select(value, func.min(name)).join(Product)
        .where(Product.status == "active", ProductVariant.enabled).group_by(value).order_by(value)
    )
    return [Facet(value=key, label=display) for key, display in rows]


def search_products(
    session: Session, filters: ProductFilters, currency: str | None, *,
    include_facets: bool = False, image_cdn_url: str | None = None,
) -> ProductPage:
    if filters.min_price is not None and filters.max_price is not None and filters.min_price > filters.max_price:
        raise CatalogError("Minimum price must be less than or equal to maximum price.")

    conditions = [Product.status == "active"]
    for kind, slugs in (("audience", filters.audience), ("clothing_type", filters.clothing_type)):
        if slugs:
            conditions.append(exists().where(
                ProductCategory.product_id == Product.id, ProductCategory.category_id == Category.id,
                Category.kind == kind, Category.slug.in_(slugs),
            ))
    if filters.min_price is not None:
        conditions.append(Product.price_minor >= filters.min_price)
    if filters.max_price is not None:
        conditions.append(Product.price_minor <= filters.max_price)
    if currency and (filters.min_price is not None or filters.max_price is not None):
        conditions.append(Product.currency == currency)
    for token in (filters.title or "").replace("\x00", "").split():
        conditions.append(Product.name.icontains(token, autoescape=True))
    for token in (filters.q or "").replace("\x00", "").split():
        conditions.append(or_(
            Product.name.icontains(token, autoescape=True),
            Product.description.icontains(token, autoescape=True),
        ))

    enabled = (ProductVariant.product_id == Product.id, ProductVariant.enabled)
    available = exists().where(*enabled, ProductVariant.stock_quantity > 0).label("in_stock")
    variant_conditions = []
    for column, values in ((ProductVariant.size_key, filters.size), (ProductVariant.color_key, filters.color)):
        terms = [variant_key(value.replace("\x00", "")) for value in values]
        matches = [column.contains(term, autoescape=True) for term in terms if term]
        if matches:
            variant_conditions.append(or_(*matches))
    if filters.in_stock:
        variant_conditions.append(ProductVariant.stock_quantity > 0)
    if variant_conditions:
        conditions.append(exists().where(*enabled, *variant_conditions))
    sort = {
        "name": (func.lower(Product.name), Product.id),
        "price_asc": (Product.price_minor, Product.id),
        "price_desc": (Product.price_minor.desc(), Product.id),
        "newest": (Product.first_published_at.desc(), Product.id.desc()),
    }[filters.sort]
    cover_id = (
        select(ProductImage.id)
        .where(ProductImage.product_id == Product.id, ProductImage.state == "ready")
        .order_by(ProductImage.sort_order, ProductImage.id)
        .limit(1).correlate(Product).scalar_subquery()
    )
    rows = session.exec(
        select(Product, available, ProductImage).outerjoin(ProductImage, ProductImage.id == cover_id)
        .where(*conditions).order_by(*sort)
        .offset((filters.page - 1) * filters.page_size).limit(filters.page_size)
    ).all()
    return ProductPage(
        items=[summarize(product, in_stock, cover, image_cdn_url) for product, in_stock, cover in rows],
        page=filters.page, page_size=filters.page_size,
        total=session.exec(select(func.count()).select_from(Product).where(*conditions)).one(),
        currency=currency,
        sizes=filter_facets(session, ProductVariant.size_key, ProductVariant.size) if include_facets else [],
        colors=filter_facets(session, ProductVariant.color_key, ProductVariant.color) if include_facets else [],
    )


def product_detail(session: Session, slug: str, *, image_cdn_url: str | None = None) -> ProductDetail | None:
    product = session.exec(
        select(Product).where(Product.slug == slug, Product.status == "active")
    ).one_or_none()
    if product is None:
        return None
    variants = [
        VariantSummary(sku=row.sku, size=row.size, color=row.color, in_stock=row.stock_quantity > 0)
        for row in session.exec(select(ProductVariant).where(
            ProductVariant.product_id == product.id, ProductVariant.enabled,
        ).order_by(ProductVariant.id))
    ]
    images = gallery(session, product.id)
    summary = summarize(
        product, any(variant.in_stock for variant in variants), images[0] if images else None, image_cdn_url,
    )
    return ProductDetail(
        **summary.model_dump(), description=product.description, categories=catalog_categories(session, product.id),
        variants=variants, images=[thumbnail(image, image_cdn_url) for image in images],
    )
