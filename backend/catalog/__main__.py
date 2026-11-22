import argparse
import json
import logging
import sys
import time
from pathlib import Path
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, select

from database import create_database_engine
from models import Category, Product, ProductCategory, ProductImage, ProductVariant

from .media import (
    clean_catalog, download_original, move_image, reconcile_catalog, remove_image, reorder_images, upload_image,
)
from .service import (
    CATEGORY_KINDS, CatalogError, CatalogSettings, label, lock_product, set_categories, set_price,
    set_status, slug_value, upsert_category, upsert_variant,
)
from .storage import R2Storage, register_location


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Manage the clothing catalog and its R2 photo library.")
    commands = cli.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create a draft product.")
    edit = commands.add_parser("edit", help="Edit an existing product.")
    create.add_argument("name")
    create.add_argument("--slug", required=True)
    edit.add_argument("product_id", type=int)
    edit.add_argument("--name")
    edit.add_argument("--slug")
    for command in (create, edit):
        command.add_argument("--description")
        command.add_argument("--price-minor", type=int)
    edit.add_argument("--clear-price", action="store_true")
    commands.add_parser("list", help="List all products, including drafts and archived items.")
    preview = commands.add_parser("preview", help="Show full product, variant, and media records.")
    preview.add_argument("product_id", type=int)
    category = commands.add_parser("category", help="Add or edit a category.")
    category.add_argument("kind", choices=CATEGORY_KINDS)
    category.add_argument("slug")
    category.add_argument("name")
    category.add_argument("--order", type=int, default=0)
    assign = commands.add_parser("assign", help="Set a product's complete category assignment.")
    assign.add_argument("product_id", type=int)
    assign.add_argument("categories", metavar="KIND:SLUG", nargs="*")
    variant = commands.add_parser("variant", help="Add or edit a product SKU.")
    variant.add_argument("product_id", type=int)
    variant.add_argument("sku")
    variant.add_argument("size")
    variant.add_argument("color")
    variant.add_argument("stock", type=int)
    variant.add_argument("--disabled", action="store_true")
    for action, help_text in (
        ("publish", "Publish a completed product."),
        ("draft", "Return a product to draft."),
        ("archive", "Archive a product."),
    ):
        command = commands.add_parser(action, help=help_text)
        command.add_argument("product_id", type=int)
    register = commands.add_parser("register-storage", help="Register an existing private R2 bucket.")
    register.add_argument("storage_id")
    register.add_argument("bucket")
    register.add_argument("endpoint")
    image = commands.add_parser("upload", help="Add or replace a product photo. Use '-' for standard input.")
    image.add_argument("product_id", type=int)
    image.add_argument("file")
    image.add_argument("--id", type=UUID, required=True, help="Keep this UUID when retrying an upload.")
    image.add_argument("--alt", required=True)
    image.add_argument("--storage")
    image.add_argument("--replace", type=UUID)
    order = commands.add_parser("image-order", help="Set the gallery order and cover.")
    order.add_argument("product_id", type=int)
    order.add_argument("image_ids", type=UUID, nargs="+")
    for action, help_text in (
        ("remove-image", "Remove a photo and queue its two objects for cleanup."),
        ("original", "Write a photo's original bytes to standard output."),
        ("move-image", "Verify a photo in a new bucket and switch its storage ID."),
    ):
        command = commands.add_parser(action, help=help_text)
        command.add_argument("image_id", type=UUID)
        if action == "move-image":
            command.add_argument("storage_id")
    commands.add_parser("cleanup", help="Retry deletions and reclaim expired pending uploads.")
    reconcile = commands.add_parser("reconcile", help="Report missing ready objects and stale orphan objects.")
    reconcile.add_argument("--delete-orphans", action="store_true")
    commands.add_parser("maintain", help="Run hourly cleanup and daily reconciliation.")
    return cli


def print_json(result) -> None:
    print(json.dumps(result, default=str, indent=2), flush=True)


def catalog_command(session: Session, args: argparse.Namespace, settings: CatalogSettings):
    action = args.command
    if action == "register-storage":
        return register_location(session, args.storage_id, args.bucket, args.endpoint)
    if action == "category":
        return upsert_category(session, args.kind, args.slug, args.name, args.order)
    if action == "list":
        return {"products": [row.model_dump() for row in session.exec(select(Product).order_by(Product.id))]}
    if action == "image-order":
        reorder_images(session, args.product_id, args.image_ids)
        return {"gallery_order": args.image_ids}
    if action == "preview":
        product = session.get(Product, args.product_id)
        if product is None:
            raise CatalogError("Product does not exist.")
        categories = session.exec(select(Category).join(ProductCategory).where(
            ProductCategory.product_id == product.id
        ).order_by(Category.kind, Category.sort_order, Category.id))
        variants = session.exec(select(ProductVariant).where(
            ProductVariant.product_id == product.id
        ).order_by(ProductVariant.id))
        images = session.exec(select(ProductImage).where(
            ProductImage.product_id == product.id
        ).order_by(ProductImage.sort_order, ProductImage.id))
        return {
            "product": product.model_dump(), "categories": [row.model_dump() for row in categories],
            "variants": [row.model_dump() for row in variants], "images": [row.model_dump() for row in images],
        }
    product = Product() if action == "create" else lock_product(session, args.product_id)
    if action in {"create", "edit"}:
        if args.slug is not None:
            if product.first_published_at and args.slug != product.slug:
                raise CatalogError("A published product's slug is permanent.")
            product.slug = slug_value(args.slug)
        if args.name is not None:
            product.name = label(args.name, 255, "Name")
        if args.description is not None:
            product.description = label(args.description, 8_000, "Description") if args.description.strip() else None
        if getattr(args, "clear_price", False):
            if args.price_minor is not None or product.status == "active":
                raise CatalogError("Only a draft or archived product can have its price cleared.")
            product.price_minor = product.currency = None
        if args.price_minor is not None:
            set_price(product, args.price_minor, settings.currency)
        session.add(product)
    elif action == "variant":
        return upsert_variant(
            session, product, args.sku, args.size, args.color, args.stock, not args.disabled, settings.currency,
        )
    elif action == "assign":
        set_categories(session, product, args.categories, settings.currency)
    else:
        set_status(session, product, {"publish": "active", "draft": "draft", "archive": "archived"}[action],
                   settings.currency)
    return product


def main() -> int:
    args = parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    engine = create_database_engine()
    try:
        settings = CatalogSettings()
        storage = R2Storage(settings)
        match args.command:
            case "upload":
                kwargs = {"storage_id": args.storage, "replace": args.replace}
                if args.file == "-":
                    result = upload_image(
                        engine, storage, settings, args.product_id, args.id, sys.stdin.buffer, args.alt, **kwargs,
                    )
                else:
                    with Path(args.file).open("rb") as source:
                        result = upload_image(
                            engine, storage, settings, args.product_id, args.id, source, args.alt, **kwargs,
                        )
            case "remove-image":
                remove_image(engine, args.image_id, settings.currency)
                result = {"image_id": args.image_id, "state": "deleting"}
            case "original":
                download_original(engine, storage, args.image_id, sys.stdout.buffer)
                return 0
            case "move-image":
                move_image(engine, storage, args.image_id, args.storage_id)
                result = {"image_id": args.image_id, "storage_id": args.storage_id}
            case "cleanup":
                result = clean_catalog(engine, storage)
            case "reconcile":
                result = reconcile_catalog(engine, storage, delete_orphans=args.delete_orphans)
            case "maintain":
                if not settings.storage_credentials:
                    raise CatalogError("Configure R2 credentials before starting catalog maintenance.")
                rounds = 0
                while True:
                    print_json({"cleanup": clean_catalog(engine, storage)})
                    if rounds % 24 == 0:
                        print_json({"reconciliation": reconcile_catalog(engine, storage)})
                    rounds += 1
                    time.sleep(3600)
            case _:
                with Session(engine, expire_on_commit=False) as session, session.begin():
                    result = catalog_command(session, args, settings)
        print_json(result if isinstance(result, dict) else result.model_dump())
        return int(isinstance(result, dict) and bool(result.get("failures")))
    except (CatalogError, OSError) as exc:
        print(str(exc), file=sys.stderr)
    except ValidationError:
        print("Check catalog configuration and the credential JSON format.", file=sys.stderr)
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        print(f"Catalog data conflicts with a database constraint ({constraint or 'check input'}).", file=sys.stderr)
    except (BotoCoreError, ClientError):
        print("The R2 operation failed. Check bucket, credentials, and connectivity, then retry.", file=sys.stderr)
    except SQLAlchemyError:
        print("Could not complete the catalog database operation.", file=sys.stderr)
    finally:
        engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
