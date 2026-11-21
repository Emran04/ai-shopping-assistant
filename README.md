# Ecomm Assistant

The FastAPI service lives in `backend/`. The Next.js homepage and its shopping chat live in `frontend/`.

## Run locally

Start the backend from the repository root. FastAPI loads its OpenAI settings from `backend/.env`.

```sh
uv --directory backend run --locked uvicorn main:app --reload
```

In a second terminal, start the frontend from the repository root.

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open [the homepage](http://localhost:3000). The frontend forwards messages to FastAPI at `http://127.0.0.1:8000`. To use another address, set `FASTAPI_URL` in `frontend/.env.local` and restart Next.js. FastAPI's interactive documentation is at [localhost:8000/docs](http://127.0.0.1:8000/docs).

Open **Shopping chat** in the bottom-right corner. FastAPI streams text to the panel as the model generates it, and **Stop** cancels the current reply. The API receives only the current question, so include relevant context in follow-up questions.

FastAPI serves newline-delimited JSON at `POST /chat/stream`. Each line is a `delta`, `done`, or `error` event. The existing `POST /chat` returns a single JSON reply.
