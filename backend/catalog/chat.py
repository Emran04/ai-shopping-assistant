import asyncio
import logging

from langchain_core.tools import tool
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from .queries import ProductFilters, search_products
from .service import CatalogError


logger = logging.getLogger(__name__)


def product_search_tool(engine: Engine, currency: str | None):
    def lookup(filters: ProductFilters) -> dict:
        with Session(engine) as session:
            result = search_products(session, filters, currency)
        return {
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

    @tool
    async def catalog_search(
        audience: list[str] | None = None, clothing_type: list[str] | None = None,
        size: list[str] | None = None, color: list[str] | None = None,
        max_price_minor: int | None = None, in_stock: bool = True, query: str | None = None,
    ) -> dict:
        """Find up to five published clothing products with prices and links.

        Use audience slugs men, women, kids and clothing type slugs such as t-shirts,
        shirts, trousers, dresses, or outerwear. Supply query only for remaining
        product keywords. Use the store currency's minor units for the price limit.
        """
        try:
            filters = ProductFilters(
                audience=audience or [], clothing_type=clothing_type or [], size=size or [], color=color or [],
                max_price=max_price_minor, in_stock=in_stock, q=query, page_size=5,
            )
            return await asyncio.to_thread(lookup, filters)
        except (CatalogError, ValidationError):
            return {"error": "The search filters are invalid."}
        except SQLAlchemyError as exc:
            logger.warning("Shopping catalog query unavailable error=%s", type(exc).__name__)
            return {"error": "The catalog is temporarily unavailable."}

    return catalog_search
