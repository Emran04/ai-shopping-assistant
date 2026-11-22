import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing, asynccontextmanager
from json import dumps
from os import getenv
from pathlib import Path
from typing import Annotated
from uuid import UUID
from weakref import WeakValueDictionary

import logfire
from catalog.chat import product_search_tool
from catalog.queries import ProductSummary
from catalog.routes import router as catalog_router
from catalog.service import CatalogSettings
from catalog.storage import R2Storage
from chatbot.agent import build_graph, run_reply, stream_reply
from chatbot.llm import Settings, create_chat_model
from database import create_database_engine, get_session
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from models import Product
from openai import APIError, APITimeoutError
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select
from starlette.types import Receive, Scope, Send

CHAT_STREAM_TYPE = "application/x-ndjson"
TIMEOUT_DETAIL = "Model request timed out."
PROVIDER_ERROR_DETAIL = "OpenAI request failed."


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    thread_id: UUID | None = None
    message_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None

    def human_message(self) -> HumanMessage:
        message_id = f"user:{self.message_id}" if self.message_id is not None else None
        return HumanMessage(content=self.message, id=message_id)


class ChatReply(BaseModel):
    reply: str
    products: list[ProductSummary] = Field(default_factory=list)


class ChatStreamingResponse(StreamingResponse):
    def __init__(self, events: AsyncGenerator[str]):
        super().__init__(
            events,
            media_type=CHAT_STREAM_TYPE,
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )
        self.events = events

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_events():
            async with aclosing(self.events):
                await self.stream_response(send)

        # A single cancellation lets LangGraph finish cleaning up its model task.
        stream = asyncio.create_task(send_events())
        disconnect = asyncio.create_task(self.listen_for_disconnect(receive))
        try:
            done, _ = await asyncio.wait((stream, disconnect), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            disconnect.cancel()
            stream.cancel()
            await asyncio.gather(stream, disconnect, return_exceptions=True)


async def stream_chat_events(chunks: AsyncGenerator[dict]) -> AsyncGenerator[str]:
    try:
        async with aclosing(chunks):
            async for event in chunks:
                yield dumps(event) + "\n"
    except (APITimeoutError, TimeoutError):
        yield dumps({"type": "error", "detail": TIMEOUT_DETAIL}) + "\n"
    except APIError:
        yield dumps({"type": "error", "detail": PROVIDER_ERROR_DETAIL}) + "\n"
    else:
        yield '{"type":"done"}\n'


def create_app(model=None):
    @asynccontextmanager
    async def lifespan(app):
        settings = Settings()
        catalog_settings = CatalogSettings()
        app.state.catalog_settings = catalog_settings
        app.state.catalog_storage = R2Storage(catalog_settings)
        client = model if model is not None else create_chat_model(settings)
        engine = create_database_engine()
        try:
            catalog_tool = product_search_tool(engine, catalog_settings.currency) if hasattr(client, "bind_tools") else None
            graph_options = {"catalog_tool": catalog_tool, "currency": catalog_settings.currency}
            app.state.graph = build_graph(client, **graph_options) if client is not None else None
            app.state.memory_graph = (
                build_graph(client, InMemorySaver(), **graph_options) if client is not None else None
            )
            app.state.thread_locks = WeakValueDictionary()
            app.state.model_name = settings.openai_model
            app.state.database_engine = engine
            yield
        finally:
            engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(catalog_router)
    logfire.instrument_fastapi(app, capture_headers=False, request_attributes_mapper=lambda *_: {})

    @asynccontextmanager
    async def chat_graph(thread_id: UUID | None):
        if thread_id is None:
            yield app.state.graph, None
            return

        lock = app.state.thread_locks.setdefault(thread_id, asyncio.Lock())
        config: RunnableConfig = {"configurable": {"thread_id": str(thread_id)}}
        async with lock:
            yield app.state.memory_graph, config

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/health/db")
    def database_health(session: Annotated[Session, Depends(get_session)]):
        try:
            session.exec(select(Product.id).limit(1)).first()
        except SQLAlchemyError:
            raise HTTPException(503, "Database is unavailable.") from None
        return {"status": "ok"}

    @app.post("/chat", response_model_exclude_defaults=True)
    async def chat(body: ChatRequest) -> ChatReply:
        if app.state.graph is None:
            raise HTTPException(503, "Configure OPENAI_API_KEY.")
        try:
            async with chat_graph(body.thread_id) as (graph, config):
                reply = await run_reply(graph, body.human_message(), app.state.model_name, config)
        except (APITimeoutError, TimeoutError):
            raise HTTPException(504, TIMEOUT_DETAIL) from None
        except APIError:
            raise HTTPException(502, PROVIDER_ERROR_DETAIL) from None
        return ChatReply(reply=reply.text, products=reply.response_metadata.get("catalog_products", []))

    @app.post(
        "/chat/stream",
        response_class=StreamingResponse,
        responses={200: {"content": {CHAT_STREAM_TYPE: {}}}},
    )
    async def chat_stream(body: ChatRequest):
        if app.state.graph is None:
            raise HTTPException(503, "Configure OPENAI_API_KEY.")

        async def chunks():
            async with chat_graph(body.thread_id) as (graph, config):
                async with aclosing(stream_reply(graph, body.human_message(), app.state.model_name, config)) as events:
                    async for event in events:
                        yield event

        return ChatStreamingResponse(stream_chat_events(chunks()))

    return app


# The wizard saves credentials at the repository root, while uv runs the API from backend/.
repository_logfire_dir = Path(__file__).resolve().parents[1] / ".logfire"
logfire.configure(
    service_name=getenv("LOGFIRE_SERVICE_NAME") or getenv("OTEL_SERVICE_NAME") or "ecomm-assistant-api",
    send_to_logfire=None if getenv("LOGFIRE_SEND_TO_LOGFIRE") else "if-token-present",
    data_dir=getenv("LOGFIRE_CREDENTIALS_DIR") or (repository_logfire_dir if repository_logfire_dir.is_dir() else None),
)
app = create_app()
