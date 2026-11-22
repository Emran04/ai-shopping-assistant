# Clothing product catalog and Cloudflare R2 images

## 1. Storefront and catalog workflow

Shoppers can browse Men, Women, and Kids, filter by clothing type, price, size, and color, and open a product page with its price, available variants, and image gallery. Products that fit multiple audiences can appear in each relevant category. Start with clothing types such as T-shirts, Shirts, Trousers, Dresses, and Outerwear. A category has a name, a stable slug, and a group (`audience` or `clothing_type`).

Staff create a draft, enter its price and categories, add size and color variants, and upload photos with descriptive alt text. They can preview the details before publishing. The first ready image in the gallery order is the cover. An active product needs a price in the configured store currency, at least one audience category, one enabled variant, and one ready image. An active product may be sold out. Staff can return it to draft for edits or archive it to remove it from the storefront.

The launch design uses a single store currency, one price per product, and a stock count per SKU. Configure the currency before entering prices. A green T-shirt in sizes S, M, and L has three SKUs with independent stock counts. Checkout, payments, and stock reservations belong to a separate implementation.

## 2. PostgreSQL data model

Extend the existing SQLModel models and add an Alembic migration after `0001`. Keep the current integer product IDs and names. Backfill existing rows as drafts with unique temporary slugs such as `product-42`, leaving the price and category assignments for staff to enter. Make the slug stable after first publication so product links remain valid. Keep the existing database health check working through the migration.

| Table | Fields and rules |
| --- | --- |
| `products` | Existing `id` and `name`, unique `slug`, optional `description`, `price_minor`, `currency`, `status` (`draft`, `active`, `archived`), and timestamps including `first_published_at`. Store prices as nonnegative integers in the currency’s minor unit. Price and currency are set together and required for active rows. Format the amount using the currency’s minor-unit precision. |
| `categories` | `id`, `group`, `name`, `slug`, and `sort_order`. Unique on `(group, slug)`. Seed Men, Women, and Kids and the initial clothing types in the migration. |
| `product_categories` | `product_id` and `category_id` form a composite primary key and reference their parent tables. Index `(category_id, product_id)` for category browsing. |
| `product_variants` | `id`, `product_id`, globally unique `sku`, `size`, `color`, nonnegative `stock_quantity`, and `enabled`. Trim and normalize size and color for uniqueness per product. Preserve their display labels. Both size and color are required, with “One size” available where applicable. |
| `media_storage_locations` | Stable `storage_id` such as `r2-catalog-prod-01`, `provider`, `bucket_name`, and `endpoint_url`. Credentials live in deployment secrets keyed by storage ID. Register a new ID for a different account or bucket. |
| `product_images` | UUID `id`, `product_id`, `storage_id` foreign key, `original_key`, `thumbnail_key`, `alt_text`, `sort_order`, timestamps, and state (`pending`, `ready`, `deleting`, `deleted`). Index `(product_id, state, sort_order, id)` for gallery reads and `(state, updated_at)` for cleanup. Use the image ID as the tie-breaker in the gallery. |

Serialize publication and catalog mutations that can affect eligibility with a lock on the product row. Prevent an active product from losing its last eligible category, enabled variant, or ready image. Expose archive as the normal removal operation and restrict direct deletes of products and storage locations that still have media records. Use the catalog service for staff changes and retain Adminer for inspection by making its catalog role read-only.

## 3. R2 location and delivery

Use a private Cloudflare R2 bucket for each environment. Configure the Python `boto3` S3 client with the account’s R2 endpoint and region `auto`. Give the API process a bucket-scoped read-only token. Run staff and cleanup commands separately with a bucket-scoped read/write token. Keep tokens in backend deployment secrets. [Cloudflare boto3 setup](https://developers.cloudflare.com/r2/examples/aws/boto3/), [R2 API token permissions](https://developers.cloudflare.com/r2/api/tokens/)

Each image row identifies one storage location and two object keys. For product 42, those values could be:

| Field | Example |
| --- | --- |
| `storage_id` | `r2-catalog-prod-01` |
| `original_key` | `products/42/8f8a8723-44cd-4d6b-8bf1-2794e82f936f/original-<sha256>.jpg` |
| `thumbnail_key` | `products/42/8f8a8723-44cd-4d6b-8bf1-2794e82f936f/thumbnail.webp` |

PostgreSQL stores object keys, the storage ID, and catalog metadata such as alt text and state. R2 stores the original and thumbnail bytes. The backend resolves `storage_id` on each media read, so existing images remain addressable when the default location for new uploads changes. To move existing media, copy and verify both objects, switch the image’s storage ID in one database transaction, then queue cleanup of the old keys after the cutover is verified. Keep the old storage profile available until cleanup completes.

FastAPI streams thumbnails by product and image ID after checking that the product is active and the image is ready. Use `Cache-Control: private, no-cache` so a browser must revalidate a cached thumbnail before reuse. Keep originals byte-for-byte for staff downloads through the catalog command. The storefront gallery uses the processed thumbnails, including on product detail pages.

## 4. Upload, replacement, and cleanup

1. Add a staff command that calls the catalog service directly and accepts a local file or standard input. Require an existing product and alt text. Start with single-frame JPEG, PNG, or WebP, a 10 MiB input limit, and a 24-megapixel decoded limit. Detect the format from the file, check dimensions before full decode, and reject corrupt, animated, or oversized files. Apply the EXIF orientation to the thumbnail, preserve aspect ratio and transparency, and make a metadata-free WebP that fits within 768 × 768 pixels without enlarging small inputs. Derive the original extension and content type from the detected format. [Pillow image processing](https://pillow.readthedocs.io/en/stable/reference/Image.html), [Pillow orientation handling](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html)
2. Use a caller-provided upload UUID as the retry key. Include the source SHA-256 in the original key so a retry can validate the file against the recorded key even if the first write never reached R2. Save a `pending` row with both keys and the resolved storage ID before writing to R2. Retain that location on retries. Upload both objects with the correct content types and a SHA-256 in object metadata, using create-only writes. When an object already exists for a pending retry, verify its length and checksum metadata against the prepared object. Reuse the same thumbnail settings for pending retries and issue a new upload ID if processing settings change and the expected thumbnail differs. [R2 S3 compatibility and conditional writes](https://developers.cloudflare.com/r2/api/s3/api/)
3. Mark the row `ready` in a short transaction once both writes are confirmed. Keep a PostgreSQL session advisory lock per image during upload and cleanup on a dedicated connection, with short database transactions and bounded R2 calls. Release the lock before returning the connection. Use the product lock in the final database transaction to serialize gallery changes. A repeat of a completed upload returns the same image. A partial write remains hidden and can be resumed. [PostgreSQL advisory locks](https://www.postgresql.org/docs/15/explicit-locking.html#ADVISORY-LOCKS)
4. Replace an image by preparing a new pair at new keys. Once both objects are confirmed, check that the old image is still ready under the product lock. Mark the replacement `ready` at the old gallery position and mark the previous row `deleting` in the same transaction. For ordinary removal, set `deleting` when the product still meets its publication requirements. Stop serving a row as soon as it leaves `ready`. The cleanup command deletes both keys, treats an already missing object as success, and records `deleted` after both deletes succeed.
5. Schedule cleanup hourly. Retry incomplete removals and reclaim pending uploads older than 24 hours after rechecking their state under the image lock. Add a periodic reconciliation command that reports missing ready objects and old objects with no live reference in the managed prefix. Have it recheck references under the image lock before deleting an orphan. Track pending age, failed uploads, and cleanup failures through the existing logging and tracing. Keep credential values and file contents out of logs.

## 5. Read API and storefront

| FastAPI route | Response |
| --- | --- |
| `GET /catalog/categories` | Categories grouped by audience and clothing type, in display order. |
| `GET /catalog/products` | Paginated active products with slug, name, price, currency, availability, and cover thumbnail URL and alt text. Accept audience, clothing type, price bounds, size, color, and an in-stock filter. |
| `GET /catalog/products/{slug}` | An active product’s description, categories, price, enabled variants with availability, and ordered thumbnail gallery. Return 404 for a missing or unpublished product. |
| `GET /catalog/media/{product_id}/{image_id}/thumbnail` | Stream the R2 WebP and close the upstream body on completion or disconnect. Return 404 for unpublished, missing, or non-ready media and 503 for an upstream outage. |

Match any selected value within a category group and combine different filter groups. When size, color, and stock filters appear together, a single enabled variant must satisfy all three. Use a stable sort with product ID as the tie-breaker and a bounded page size. Keep Postgres as the source of price and availability.

Reuse the existing FastAPI database session setup and Next.js `FASTAPI_URL` convention. Add storefront list and detail views with filters, alt text, unavailable-variant states, and placeholders for media that fails to load. Route browser media requests through a narrow same-origin Next.js handler that forwards only known thumbnail routes and preserves the backend’s cache policy. After the catalog works end to end, the shopping assistant can reuse the catalog query service to ground product recommendations in actual prices, links, and availability.

## 6. Implementation sequence

1. **Schema and draft migration.** Extend SQLModel, seed categories, review Alembic constraints and indexes, and run the migration on a fresh database and one containing existing products. Confirm `GET /health/db` still works.
2. **Staff workflow and R2.** Add the catalog commands for product, variant, category, and image management. Pin Python 3.14-compatible `boto3` and Pillow dependencies in the backend lockfile. Configure a test storage profile, run an upload and download against R2, and verify data recovery before enabling scheduled cleanup.
3. **Catalog reads and storefront.** Add FastAPI routes, filter queries, product and gallery views, and consistent price and availability displays. Exercise the complete draft-to-published flow with sample clothing products.
4. **Production rollout.** Register the production R2 location and inject its bucket-scoped secrets. Deploy the migration and application, verify a real product and both object renditions, then enable cleanup scheduling and monitoring. Back up the database before schema changes and verify that a restore preserves storage IDs.

## 7. Acceptance checks

- A pre-existing product retains its ID and name, becomes a draft, and appears in public results only after staff complete and publish it.
- A T-shirt assigned to Men and Women appears in both. Kids is independently browsable. Category, price, size, and color filters produce stable pages, and an in-stock size/color match comes from the same SKU.
- Prices round-trip exactly in the configured currency. Negative prices, duplicate SKUs, and publication without required fields or images are rejected.
- A valid upload creates two R2 objects. The original matches the input bytes. The thumbnail opens as WebP with the expected orientation, dimensions, and metadata removal. Invalid uploads create no visible images.
- An interrupted upload, a duplicate retry, and an interrupted delete recover without broken public listings. Replacing the cover keeps a valid cover available. Losing R2 access affects media delivery while product details remain available.
- Archived and draft products and their thumbnails stay private from storefront requests. A second location can serve new uploads while earlier images still resolve through their stored location IDs.
