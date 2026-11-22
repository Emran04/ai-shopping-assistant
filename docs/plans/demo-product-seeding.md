# Demo clothing catalog and seeding plan

## Demo inventory

The demo catalog contains 60 fictional listings, with 20 each for Men, Women, and Kids. Each listing has one locally stored cover photo, a description, a demo price in USD minor units, and size variants for the color shown. The prices, sizes, and stock counts are fixture values. Include in-stock and sold-out listings so the storefront and shopping assistant have both cases to demonstrate.

The workspace contains the inventory, image files, and their provenance. The JSON manifest is the source of truth for the product list.

| Path | Contents |
| --- | --- |
| `data/demo-products.json` | Product keys, slugs, descriptions, categories, prices, variant SKUs, stock, and local and R2 cover paths |
| `data/images/demo/` | One JPEG per product, named after its stable demo key |
| `data/demo-image-sources.json` | Source image IDs and pinned URLs, source labels, license, dimensions, and SHA-256 hashes |

The photos come from Alexey Grigorev’s CC0 Clothing Dataset. The source marks children’s garments, and the demo assigns the adult audience for merchandising. The files and their hashes belong in the repo so a fresh checkout can seed the same catalog without fetching from GitHub. Keep the source manifest beside the photos when copying the fixture. [Dataset and license](https://github.com/alexeygrigorev/clothing-dataset/tree/7ed86a9cc56763b6acb35e41cb35184e43a5d218), [CC0 license](https://creativecommons.org/publicdomain/zero/1.0/)

## Seeder command

1. Add `python -m catalog seed-demo` to the existing catalog CLI. Support `--dry-run` that validates the complete fixture, reports intended creates and updates, and performs zero database or R2 writes. Resolve photo paths under `data/`, verify their hashes, and enforce the upload service’s file limits before starting.
2. Give every fixture item a permanent key such as `demo-men-01`. Persist a unique mapping from the key to the product ID so changes to a name or manifest order never create a new product. Keep the existing slug once a demo product has been published. Report a conflict when a slug or SKU belongs to a product outside the fixture.
3. Upsert clothing types, products, category assignments, and variants through the existing catalog service. Compare current values before updating. Treat the fixture as authoritative for its own prices and stock. Require the configured store currency to match an available fixture price book. The first price book is USD. Add explicitly priced amounts for any other demo currency.
4. Verify the original and WebP thumbnail already uploaded to the registered demo R2 storage ID. Attach their manifest keys as ready product covers. A cover replacement keeps the shared files available to future seed runs. Publish each product after its required fields, variants, and cover are ready.
5. Serialize seed runs per database and apply the fixture in one transaction. Report counts for created, updated, and unchanged items. A failure rolls back the database changes so the command can be retried. Keep items removed from the fixture until staff explicitly archive them.

## Keep demos available

Add a demo Compose override with a one-shot seed job. In that configuration, the job runs after database migrations and the API waits for its successful completion. Point it at a dedicated demo database and private R2 bucket. Share the local fixture directory read-only with the seed job. Use read/write R2 credentials for the seed job and retain read-only R2 credentials for the API.

A fresh demo database gets all 60 products. A restart checks and restores the intended demo state. An ordinary deployment uses the standard Compose configuration and its own data. To change the demo assortment, update the manifest and image files together, preview the change with `--dry-run`, then run the seed job again.

## Verification

- Run the seeder on a fresh demo database. Verify 60 published products, 20 for each audience, unique SKUs, one ready cover per product, and both object keys resolving through the demo storage ID.
- Run it again against the same database. Confirm the product IDs, variant IDs, upload IDs, and R2 object count stay the same.
- Seed against a missing thumbnail key. The command should fail before changing any products and succeed when the complete image pair is available.
- Change one cover in the manifest. Verify the product keeps its URL, the new cover appears, and the old shared fixture stays available.
- Confirm demo seeding preserves an unrelated product. Verify price and size filters, sold-out results, and chat links against the seeded catalog.
