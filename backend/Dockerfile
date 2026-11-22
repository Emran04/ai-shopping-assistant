FROM ghcr.io/astral-sh/uv:0.11.19 AS uv
FROM python:3.14-slim

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
