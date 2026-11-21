import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing, asynccontextmanager
from json import dumps
from typing import Annotated

import logfire
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIError, APITimeoutError
from pydantic import BaseModel, StringConstraints
from starlette.types import Receive, Scope, Send

from chatbot.agent import build_graph
from chatbot.llm import Settings, create_chat_model


CHAT_STREAM_TYPE = "application/x-ndjson"
TIMEOUT_DETAIL = "Model request timed out."
PROVIDER_ERROR_DETAIL = "OpenAI request failed."


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChatReply(BaseModel):
    reply: str


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


async def stream_reply(graph, message: str, model_name: str) -> AsyncGenerator[str]:
    with logfire.span("Stream assistant graph", model=model_name) as span:
        try:
            events = graph.astream(
                {"messages": [HumanMessage(content=message)]},
                stream_mode="messages",
                version="v2",
            )
            async with aclosing(events):
                async for event in events:
                    chunk, metadata = event["data"]
                    if metadata.get("langgraph_node") != "assistant" or not isinstance(chunk, AIMessage):
                        continue
                    if text := chunk.text:
                        yield dumps({"type": "delta", "text": text}) + "\n"
        except (APITimeoutError, TimeoutError):
            span.set_attribute("outcome", "timeout")
            yield dumps({"type": "error", "detail": TIMEOUT_DETAIL}) + "\n"
        except APIError:
            span.set_attribute("outcome", "provider_error")
            yield dumps({"type": "error", "detail": PROVIDER_ERROR_DETAIL}) + "\n"
        else:
            span.set_attribute("outcome", "success")
            yield '{"type":"done"}\n'


def create_app(model=None):
    @asynccontextmanager
    async def lifespan(app):
        settings = Settings()
        client = model if model is not None else create_chat_model(settings)
        app.state.graph = build_graph(client) if client is not None else None
        app.state.model_name = settings.openai_model
        yield

    app = FastAPI(lifespan=lifespan)
    logfire.configure(send_to_logfire="if-token-present")
    logfire.instrument_fastapi(app, capture_headers=False, request_attributes_mapper=lambda *_: {})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/chat")
    async def chat(body: ChatRequest) -> ChatReply:
        if app.state.graph is None:
            raise HTTPException(503, "Configure OPENAI_API_KEY.")
        with logfire.span("Run assistant graph", model=app.state.model_name) as span:
            try:
                state = await app.state.graph.ainvoke(
                    {"messages": [HumanMessage(content=body.message)]}
                )
            except (APITimeoutError, TimeoutError):
                span.set_attribute("outcome", "timeout")
                raise HTTPException(504, TIMEOUT_DETAIL) from None
            except APIError:
                span.set_attribute("outcome", "provider_error")
                raise HTTPException(502, PROVIDER_ERROR_DETAIL) from None
            span.set_attribute("outcome", "success")
            return ChatReply(reply=state["messages"][-1].text)

    @app.post(
        "/chat/stream",
        response_class=StreamingResponse,
        responses={200: {"content": {CHAT_STREAM_TYPE: {}}}},
    )
    async def chat_stream(body: ChatRequest):
        if app.state.graph is None:
            raise HTTPException(503, "Configure OPENAI_API_KEY.")
        return ChatStreamingResponse(stream_reply(app.state.graph, body.message, app.state.model_name))

    return app


app = create_app()
