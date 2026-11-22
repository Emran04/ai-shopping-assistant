# Ecomm Assistant

The FastAPI service lives in `backend/`. The Next.js storefront and shopping chat live in `frontend/`.

## Run FastAPI and PostgreSQL with Docker

From the repository root, run:

```sh
docker compose up --build --wait
curl -fsS http://127.0.0.1:8000/health/db
```

Compose starts PostgreSQL, runs `alembic upgrade head`, and then starts FastAPI. The database check queries the `products` table from the initial migration. PostgreSQL data is stored in the `postgres-data` volume and survives `docker compose down`.

Set `OPENAI_API_KEY` in `backend/.env` to enable chat. The database check and [FastAPI docs](http://127.0.0.1:8000/docs) work without a key.

### Browse data in Adminer

Open [Adminer](http://127.0.0.1:8080) and log in with **PostgreSQL** as the system, `db` as the server, `admin` as the username, `123` as the password, and `ecomm_assistant` as the database. The `admin` role has read-only access. Set `ADMINER_PORT` in the root `.env` to change the host port or `ADMINER_PASSWORD` to choose a password when the role is first created.

### Run FastAPI on the host

For live reload, run PostgreSQL in Docker and use `uv` for FastAPI:

```sh
docker compose up -d --wait db
uv --directory backend run --locked alembic upgrade head
uv --directory backend run --locked uvicorn main:app --reload
```

The local defaults are database `ecomm_assistant`, user `ecomm`, password `ecomm`, and port `5432`. To override them for Compose, set `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_FORWARD_PORT` in the root `.env`. For a host-run API, set matching values in `backend/.env` using `POSTGRES_PORT` for the forwarded port, or set `DATABASE_URL` there to a PostgreSQL connection URL.

After changing `backend/models.py`, generate and review a migration against the running database, then apply it:

```sh
uv --directory backend run --locked alembic revision --autogenerate -m "describe schema change"
uv --directory backend run --locked alembic upgrade head
```

### Run the frontend

Start Next.js from the repository root.

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open [the homepage](http://localhost:3000). The frontend forwards messages to FastAPI at `http://127.0.0.1:8000`. To use another address, set `FASTAPI_URL` in `frontend/.env.local` and restart Next.js. FastAPI's interactive documentation is at [localhost:8000/docs](http://127.0.0.1:8000/docs).

## Manage the clothing catalog

Open [Shop clothing](http://localhost:3000/catalog) to browse published products. Migration `0002` adds categories, sizes and colors, image records, and storage locations. Existing products keep their IDs and names and start as drafts.

### Connect private R2 storage

Create a private bucket in Cloudflare R2 and create separate bucket-scoped credentials for the API and staff. Add the store’s ISO currency code and read-only credentials to `backend/.env` using this format. [Cloudflare R2 credentials](https://developers.cloudflare.com/r2/api/tokens/)

```dotenv
CATALOG_CURRENCY=USD
CATALOG_STORAGE_CREDENTIALS='{"r2-catalog-dev-01":{"access_key_id":"<read-only-access-key>","secret_access_key":"<read-only-secret>"}}'
```

Use the store’s currency in place of the example USD. For staff commands, put the same currency and the following settings in `backend/.env.catalog-staff`. Keep production and development buckets and credentials separate.

```dotenv
CATALOG_CURRENCY=USD
CATALOG_DEFAULT_STORAGE_ID=r2-catalog-dev-01
CATALOG_STORAGE_CREDENTIALS='{"r2-catalog-dev-01":{"access_key_id":"<read-write-access-key>","secret_access_key":"<read-write-secret>"}}'
```

After applying migrations, define a local shell function and register the existing bucket. Use the full R2 S3 API endpoint shown by Cloudflare.

```sh
catalog() { uv --directory backend run --locked --env-file .env.catalog-staff python -m catalog "$@"; }
catalog register-storage r2-catalog-dev-01 your-private-bucket https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
```

### Create and publish a product

Run `catalog list` to find legacy product IDs. This example uses product ID 1. Substitute the ID printed by `create` and use a real product photo.

```sh
catalog create 'Everyday T-shirt' --slug everyday-t-shirt --description 'A cotton crew-neck tee' --price-minor 2499
catalog assign 1 audience:men audience:women clothing_type:t-shirts
catalog variant 1 TEE-OLIVE-S S Olive 12
catalog variant 1 TEE-OLIVE-M M Olive 0
upload_id=$(uuidgen)
catalog upload 1 /path/to/photo.jpg --id "$upload_id" --alt 'Olive crew-neck T-shirt, front view'
catalog preview 1
catalog publish 1
```

Prices are entered in minor units, so `2499` means 24.99 USD. Keep the same upload UUID and file when retrying. Supply `--replace OLD_IMAGE_UUID` with a fresh upload UUID to swap a photo in place. Use `catalog original IMAGE_UUID > original.jpg` to export the original, or `catalog image-order PRODUCT_ID IMAGE_UUID …` to choose the cover and order the gallery. Run `catalog --help` for the full command list.

### Verify and maintain storage

Publish a test product and verify its listing, detail page, and thumbnail. Download the original and compare it to the input. Run `catalog reconcile` to report missing ready images and old orphaned objects. Once verified, enable the Compose maintenance profile for hourly cleanup and daily reconciliation.

```sh
docker compose --profile catalog up -d catalog-maintenance
```

For a new bucket, register another storage ID and add its credentials to both configurations before changing the staff default. Use `catalog move-image IMAGE_UUID NEW_STORAGE_ID` to copy and verify both objects, then update the stored location. The cleanup process retains the old copy for 24 hours. Keep its credentials available until cleanup completes. Use `catalog reconcile --delete-orphans` to delete old orphaned objects after reviewing the report. Back up PostgreSQL before deployment and keep the R2 credentials available to verify delivery after a restore.

### Run the catalog checks

The integration test runs migrations in a temporary schema on a test PostgreSQL database and simulates R2 responses. Set `CATALOG_TEST_DATABASE_URL` to a disposable database whose role can create schemas.

```sh
CATALOG_TEST_DATABASE_URL=postgresql://user:password@localhost/catalog_test \
  uv --directory backend run --locked python -m unittest discover -s tests
```

## Shopping chat

Open **Shopping chat** in the bottom-right corner. FastAPI streams text to the panel as the model generates it, and **Stop** cancels the current reply. The assistant remembers completed turns in the loaded page, including when you close and reopen the panel. Reloading the page starts a new chat. History lives in one FastAPI process and is cleared when that process restarts.

FastAPI serves newline-delimited JSON at `POST /chat/stream`. Each line is a `delta`, `done`, or `error` event. `POST /chat` returns a single JSON reply. Both accept `message` and an optional UUID `thread_id`. Reuse the same thread ID for follow-ups and optionally send a stable `message_id` to make retries safe. Requests without a thread ID are independent.
