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

The chat displays each reply on the page. The API receives only the current question, so include any relevant context in follow-up questions.
