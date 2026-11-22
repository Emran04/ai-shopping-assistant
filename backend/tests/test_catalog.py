import json
import os
import unittest
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from PIL import Image
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import Session

from catalog.media import clean_catalog, download_original, move_image, reconcile_catalog, remove_image, upload_image
from catalog.service import CatalogError, CatalogSettings, lock_product, set_categories, set_price, set_status, upsert_variant
from catalog.storage import prepare_image, register_location
from database import create_database_engine
from main import create_app
from models import MediaRetirement, ProductImage


def jpeg(color="olive") -> bytes:
    output = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (1000, 400), color).save(output, format="JPEG", exif=exif)
    return output.getvalue()


class ImageProcessingTests(unittest.TestCase):
    def test_original_and_oriented_thumbnail(self):
        source = jpeg()
        result = prepare_image(BytesIO(source))
        self.assertEqual(result.original, source)
        self.assertEqual(result.content_type, "image/jpeg")
        with Image.open(BytesIO(result.thumbnail)) as thumbnail:
            self.assertEqual(thumbnail.format, "WEBP")
            self.assertEqual(thumbnail.size, (307, 768))
            self.assertFalse(thumbnail.getexif())

    def test_small_transparent_images_and_invalid_files(self):
        source = BytesIO()
        Image.new("RGBA", (8, 4), (0, 0, 0, 0)).save(source, format="PNG")
        with Image.open(BytesIO(prepare_image(BytesIO(source.getvalue())).thumbnail)) as thumbnail:
            self.assertEqual(thumbnail.size, (8, 4))
            self.assertEqual(thumbnail.getpixel((0, 0))[3], 0)
        invalid_images = (b"not an image", jpeg()[:300], b"x" * (10 * 1024 * 1024 + 1))
        for invalid in invalid_images:
            with self.assertRaises(CatalogError):
                prepare_image(BytesIO(invalid))


def s3_error(operation, code):
    return ClientError({"Error": {"Code": code}}, operation)


class CatalogModel:
    def bind_tools(self, tools, *, parallel_tool_calls):
        async def request_search(messages):
            return AIMessage(content="", tool_calls=[{
                "name": tools[0].name, "id": "catalog-search", "args": {"audience": ["women"]},
            }])

        return SimpleNamespace(ainvoke=request_search)

    async def ainvoke(self, messages):
        product = json.loads(messages[-1].content)["products"][0]
        return AIMessage(content=f"[{product['name']}]({product['url']})")


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.fail_next_thumbnail = False
        self.fail_next_delete = False
        self.unavailable = False

    def open(self, location):
        if self.unavailable:
            raise s3_error("GetObject", "ServiceUnavailable")
        return nullcontext(self)

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata, IfNoneMatch):
        assert IfNoneMatch == "*"
        if Key.endswith("thumbnail.webp") and self.fail_next_thumbnail:
            self.fail_next_thumbnail = False
            raise s3_error("PutObject", "ServiceUnavailable")
        if (Bucket, Key) in self.objects:
            raise s3_error("PutObject", "PreconditionFailed")
        self.objects[Bucket, Key] = (Body, ContentType, Metadata)

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise s3_error("HeadObject", "NoSuchKey")
        body, content_type, metadata = self.objects[Bucket, Key]
        return {"ContentLength": len(body), "ContentType": content_type, "Metadata": metadata, "ETag": '"test"'}

    def get_object(self, *, Bucket, Key):
        response = self.head_object(Bucket=Bucket, Key=Key)
        body, _, _ = self.objects[Bucket, Key]
        return {**response, "Body": StreamingBody(BytesIO(body), len(body))}

    def delete_object(self, *, Bucket, Key):
        if Key.endswith("thumbnail.webp") and self.fail_next_delete:
            self.fail_next_delete = False
            raise s3_error("DeleteObject", "ServiceUnavailable")
        self.objects.pop((Bucket, Key), None)

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"

        def paginate(*, Bucket, Prefix):
            yield {"Contents": [
                {"Key": key, "LastModified": datetime.now(UTC) - timedelta(days=2)}
                for bucket, key in list(self.objects) if bucket == Bucket and key.startswith(Prefix)
            ]}

        return SimpleNamespace(paginate=paginate)


@unittest.skipUnless(os.getenv("CATALOG_TEST_DATABASE_URL"), "set CATALOG_TEST_DATABASE_URL for PostgreSQL checks")
class CatalogIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ["CATALOG_TEST_DATABASE_URL"])
        schema = "test_catalog_" + uuid4().hex
        with patch.dict(os.environ, {"DATABASE_URL": url.render_as_string(hide_password=False)}):
            server = create_database_engine()
        cls.addClassCleanup(server.dispose)
        with server.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))

        def remove_schema():
            with server.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))

        cls.addClassCleanup(remove_schema)
        scoped_url = url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
        cls.environment = {"DATABASE_URL": scoped_url, "CATALOG_CURRENCY": "USD"}
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with patch.dict(os.environ, cls.environment):
            cls.engine = create_database_engine()
            cls.addClassCleanup(cls.engine.dispose)
            command.upgrade(config, "0001")
            with cls.engine.begin() as connection:
                connection.execute(text("INSERT INTO products (name) VALUES ('Legacy shirt')"))
            command.upgrade(config, "head")

    def test_catalog_from_legacy_draft_to_publication_and_cleanup(self):
        storage = MemoryStorage()
        settings = CatalogSettings(currency="USD", default_storage_id="r2-dev-01")
        endpoint = "https://" + "a" * 32 + ".r2.cloudflarestorage.com"
        with Session(self.engine) as session, session.begin():
            product = lock_product(session, 1)
            self.assertEqual((product.id, product.name, product.slug, product.status, product.price_minor),
                             (1, "Legacy shirt", "product-1", "draft", None))
            set_price(product, 2499, settings.currency)
            set_categories(session, product, ["audience:men", "audience:women", "clothing_type:t-shirts"], "USD")
            upsert_variant(session, product, "SHIRT-S", "S", "Olive", 5, True, "USD")
            upsert_variant(session, product, "SHIRT-M", "M", "Navy", 0, True, "USD")
            register_location(session, "r2-dev-01", "sample-catalog-a", endpoint)
            register_location(session, "r2-dev-02", "sample-catalog-b", endpoint)
        with self.assertRaises(CatalogError), Session(self.engine) as session, session.begin():
            set_status(session, lock_product(session, 1), "active", settings.currency)

        source = jpeg()
        image_id = uuid4()
        media_url = f"/catalog/media/1/{image_id}/thumbnail"
        storage.fail_next_thumbnail = True
        with self.assertRaises(ClientError):
            upload_image(self.engine, storage, settings, 1, image_id, BytesIO(source), "Front view")
        with Session(self.engine) as session:
            self.assertEqual(session.get(ProductImage, image_id).state, "pending")
        with self.assertRaises(CatalogError):
            upload_image(self.engine, storage, settings, 1, image_id, BytesIO(jpeg("blue")), "Front view")
        first = upload_image(self.engine, storage, settings, 1, image_id, BytesIO(source), "Front view")
        retry = upload_image(self.engine, storage, settings, 1, image_id, BytesIO(source), "Front view")
        self.assertEqual(first.id, retry.id)
        self.assertEqual(len(storage.objects), 2)
        downloaded = BytesIO()
        download_original(self.engine, storage, image_id, downloaded)
        self.assertEqual(downloaded.getvalue(), source)

        with patch.dict(os.environ, self.environment), TestClient(create_app(CatalogModel())) as client:
            client.app.state.catalog_storage = storage
            self.assertEqual(client.get("/health/db").status_code, 200)
            self.assertEqual(client.get("/catalog/products/product-1").status_code, 404)
            self.assertEqual(client.get(media_url).status_code, 404)
            with Session(self.engine) as session, session.begin():
                set_status(session, lock_product(session, 1), "active", "USD")
            expected_reply = "[Legacy shirt](/catalog/product-1)"
            chat = client.post("/chat", json={"message": "Show me clothes for women."})
            self.assertEqual(chat.json()["reply"], expected_reply)
            streamed = client.post("/chat/stream", json={"message": "Show me clothes for women."})
            events = [json.loads(line) for line in streamed.text.splitlines()]
            self.assertEqual("".join(event["text"] for event in events if event["type"] == "delta"), expected_reply)
            for audience in ("men", "women"):
                result = client.get("/catalog/products", params={"audience": audience, "clothing_type": "t-shirts"})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["items"][0]["price_minor"], 2499)
            for filters in (
                {"audience": "kids"}, {"size": "M", "color": "Olive"},
                {"size": "M", "color": "Navy", "in_stock": True}, {"max_price": 2498},
            ):
                self.assertEqual(client.get("/catalog/products", params=filters).json()["total"], 0)
            self.assertEqual(client.get("/catalog/products?min_price=3000&max_price=2000").status_code, 422)
            detail = client.get("/catalog/products/product-1").json()
            self.assertEqual(detail["cover"]["id"], str(image_id))
            self.assertEqual([item["in_stock"] for item in detail["variants"]], [True, False])
            thumb = client.get(media_url)
            self.assertEqual(thumb.status_code, 200)
            self.assertEqual(thumb.headers["content-type"], "image/webp")
            self.assertEqual(thumb.headers["cache-control"], "private, no-cache")
            self.assertEqual(client.get(media_url, headers={"If-None-Match": thumb.headers["etag"]}).status_code, 304)
            storage.unavailable = True
            self.assertEqual(client.get(media_url).status_code, 503)
            self.assertEqual(client.get("/catalog/products/product-1").status_code, 200)
            storage.unavailable = False
            with self.assertRaises(CatalogError):
                remove_image(self.engine, image_id, "USD")

            replacement_id = uuid4()
            replacement = upload_image(
                self.engine, storage, settings, 1, replacement_id, BytesIO(jpeg("blue")), "New front",
                replace=image_id,
            )
            self.assertEqual(replacement.sort_order, first.sort_order)
            self.assertEqual(client.get(media_url).status_code, 404)
            self.assertEqual(client.get("/catalog/products/product-1").json()["cover"]["id"], str(replacement_id))
            storage.fail_next_delete = True
            self.assertEqual(clean_catalog(self.engine, storage)["failures"], 1)
            self.assertEqual(clean_catalog(self.engine, storage)["images_deleted"], 1)
            move_image(self.engine, storage, replacement_id, "r2-dev-02")
            self.assertEqual(len(storage.objects), 4)
            moved_url = f"/catalog/media/1/{replacement_id}/thumbnail"
            self.assertEqual(client.get(moved_url).status_code, 200)
            with Session(self.engine) as session, session.begin():
                retirement = session.get(MediaRetirement, (replacement_id, "r2-dev-01"))
                retirement.delete_after = datetime.now(UTC) - timedelta(seconds=1)
                self.assertEqual(session.get(ProductImage, replacement_id).storage_id, "r2-dev-02")
            self.assertEqual(clean_catalog(self.engine, storage)["copies_deleted"], 1)

            lost_key = ("sample-catalog-b", replacement.thumbnail_key)
            thumb_object = storage.objects.pop(lost_key)
            self.assertEqual(client.get(moved_url).status_code, 404)
            orphan_key = ("sample-catalog-a", f"products/1/{uuid4()}/thumbnail.webp")
            storage.objects[orphan_key] = thumb_object
            report = reconcile_catalog(self.engine, storage, delete_orphans=True)
            self.assertEqual(len(report["missing"]), 1)
            self.assertEqual(report["orphans_deleted"], 1)
            storage.objects[lost_key] = thumb_object
            with Session(self.engine) as session, session.begin():
                set_status(session, lock_product(session, 1), "archived", "USD")
            self.assertEqual(client.get(moved_url, headers={"If-None-Match": '"test"'}).status_code, 404)
            self.assertEqual(client.get("/catalog/products/product-1").status_code, 404)
