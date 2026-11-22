import asyncio
import logging
from typing import Literal

from langchain_core.tools import tool
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from .queries import ProductFilters, search_products
from .service import CatalogError


logger = logging.getLogger(__name__)
CHAT_PRODUCT_LIMIT = 8


def product_search_tool(engine: Engine, currency: str | None):
    def lookup(filters: ProductFilters) -> tuple[dict, list[dict]]:
        with Session(engine) as session:
            result = search_products(session, filters, currency)
        content = {
            "total": result.total,
            "products": [
                {
                    "name": product.name,
                    "url": f"/catalog/{product.slug}",
                    "currency": product.currency,
                    "price_minor": product.price_minor,
                    "in_stock": product.in_stock,
                }
                for product in result.items
            ],
        }
        return content, [product.model_dump(mode="json") for product in result.items]

    @tool(response_format="content_and_artifact")
    async def catalog_search(
        audience: list[str] | None = None, clothing_type: list[str] | None = None,
        size: list[str] | None = None, color: list[str] | None = None,
        min_price_minor: int | None = None, max_price_minor: int | None = None,
        in_stock: bool = False, query: str | None = None,
        sort: Literal["newest", "name", "price_asc", "price_desc"] = "newest",
    ) -> tuple[dict, list[dict]]:
        """Find up to eight published clothing products with prices and availability.

        Use audience slugs men, women, kids and clothing type slugs such as t-shirts,
        shirts, trousers, dresses, or outerwear. Supply query only for remaining
        product keywords. Use the store currency's minor units for price filters.
        Set in_stock when the shopper is interested only in available items.
        """
        try:
            filters = ProductFilters(
                audience=audience or [], clothing_type=clothing_type or [], size=size or [], color=color or [],
                min_price=min_price_minor, max_price=max_price_minor, in_stock=in_stock,
                q=query, sort=sort, page_size=CHAT_PRODUCT_LIMIT,
            )
            return await asyncio.to_thread(lookup, filters)
        except (CatalogError, ValidationError):
            return {"error": "The search filters are invalid."}, []
        except SQLAlchemyError as exc:
            logger.warning("Shopping catalog query unavailable error=%s", type(exc).__name__)
            return {"error": "The catalog is temporarily unavailable."}, []

    return catalog_search
