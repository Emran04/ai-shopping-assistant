from contextlib import asynccontextmanager
from typing import Annotated

import logfire
from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from openai import APIError, APITimeoutError
from pydantic import BaseModel, StringConstraints

from chatbot.agent import build_graph
from chatbot.llm import Settings, create_chat_model


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChatReply(BaseModel):
    reply: str


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
                raise HTTPException(504, "Model request timed out.") from None
            except APIError:
                span.set_attribute("outcome", "provider_error")
                raise HTTPException(502, "OpenAI request failed.") from None
            span.set_attribute("outcome", "success")
            return ChatReply(reply=state["messages"][-1].text)

    return app


app = create_app()
