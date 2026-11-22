# Ecomm Assistant

The FastAPI service lives in `backend/`. The Next.js homepage and its shopping chat live in `frontend/`.

## Run FastAPI and PostgreSQL with Docker

From the repository root, run:

```sh
docker compose up --build --wait
curl -fsS http://127.0.0.1:8000/health/db
```

Compose starts PostgreSQL, runs `alembic upgrade head`, and then starts FastAPI. The database check queries the `products` table from the initial migration. PostgreSQL data is stored in the `postgres-data` volume and survives `docker compose down`.

Set `OPENAI_API_KEY` in `backend/.env` to enable chat. The database check and [FastAPI docs](http://127.0.0.1:8000/docs) work without a key.

### Browse data in Adminer

Open [Adminer](http://127.0.0.1:8080) and log in with **PostgreSQL** as the system, `db` as the server, `admin` as the username, `123` as the password, and `ecomm_assistant` as the database. The `admin` role can browse the app's tables and add products. Set `ADMINER_PORT` in the root `.env` to change the host port or `ADMINER_PASSWORD` to choose a password when the role is first created.

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

Open **Shopping chat** in the bottom-right corner. FastAPI streams text to the panel as the model generates it, and **Stop** cancels the current reply. The assistant remembers completed turns in the loaded page, including when you close and reopen the panel. Reloading the page starts a new chat. History lives in one FastAPI process and is cleared when that process restarts.

FastAPI serves newline-delimited JSON at `POST /chat/stream`. Each line is a `delta`, `done`, or `error` event. `POST /chat` returns a single JSON reply. Both accept `message` and an optional UUID `thread_id`. Reuse the same thread ID for follow-ups and optionally send a stable `message_id` to make retries safe. Requests without a thread ID are independent.
