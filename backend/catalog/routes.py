import logging
from contextlib import ExitStack
from typing import Annotated
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from database import get_session
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from models import MediaStorageLocation, Product, ProductImage
from sqlmodel import Session, select

from .queries import (
    CatalogIndex,
    ProductDetail,
    ProductFilters,
    ProductPage,
    catalog_categories,
    product_detail,
    search_products,
)
from .service import CatalogError
from .storage import ObjectMissing, get_object

router = APIRouter(prefix="/catalog", tags=["catalog"])
logger = logging.getLogger(__name__)
DatabaseSession = Annotated[Session, Depends(get_session, scope="function")]


class ThumbnailResponse(StreamingResponse):
    def __init__(self, objects: ExitStack, body, headers):
        super().__init__(body.iter_chunks(64 * 1024), media_type="image/webp", headers=headers)
        self.objects = objects

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.objects.close()


@router.get("/categories")
def categories(request: Request, session: DatabaseSession) -> CatalogIndex:
    return CatalogIndex(
        **catalog_categories(session).model_dump(), currency=request.app.state.catalog_settings.currency,
    )


@router.get("/products")
def products(request: Request, filters: Annotated[ProductFilters, Query()], session: DatabaseSession) -> ProductPage:
    settings = request.app.state.catalog_settings
    try:
        return search_products(session, filters, settings.currency, include_facets=True, image_cdn_url=settings.image_cdn_url)
    except CatalogError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/products/{slug}")
def product(slug: str, request: Request, session: DatabaseSession) -> ProductDetail:
    result = product_detail(session, slug, image_cdn_url=request.app.state.catalog_settings.image_cdn_url)
    if result is None:
        raise HTTPException(404, "Product not found.")
    return result


@router.get("/media/{product_id}/{image_id}/thumbnail", response_class=StreamingResponse)
def product_thumbnail(product_id: int, image_id: UUID, request: Request, session: DatabaseSession):
    result = session.exec(
        select(MediaStorageLocation, ProductImage.thumbnail_key)
        .join(ProductImage, ProductImage.storage_id == MediaStorageLocation.storage_id)
        .join(Product, Product.id == ProductImage.product_id)
        .where(Product.id == product_id, Product.status == "active",
               ProductImage.id == image_id, ProductImage.state == "ready")
    ).one_or_none()
    if result is None:
        raise HTTPException(404, "Image not found.")
    location, key = result
    try:
        with ExitStack() as objects:
            client = objects.enter_context(request.app.state.catalog_storage.open(location))
            response = get_object(client, location.bucket_name, key)
            body = response["Body"]
            objects.callback(body.close)
            headers = {"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"}
            if etag := response.get("ETag"):
                headers["ETag"] = etag
                request_etags = request.headers.get("if-none-match", "").split(",")
                if any(tag.strip().removeprefix("W/") in {"*", etag} for tag in request_etags):
                    return Response(status_code=304, headers=headers)
            headers["Content-Length"] = str(response["ContentLength"])
            return ThumbnailResponse(objects.pop_all(), body, headers)
    except ObjectMissing:
        logger.warning("Catalog thumbnail missing image=%s storage=%s", image_id, location.storage_id)
        raise HTTPException(404, "Image not found.") from None
    except (BotoCoreError, ClientError, CatalogError) as exc:
        logger.warning("Catalog thumbnail unavailable image=%s storage=%s error=%s",
                       image_id, location.storage_id, type(exc).__name__)
        raise HTTPException(503, "Image storage is unavailable.") from None
