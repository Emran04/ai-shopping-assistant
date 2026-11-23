from collections.abc import AsyncGenerator
from operator import add
from typing import Annotated

import logfire
from catalog.chat import CHAT_PRODUCT_LIMIT
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.channels import UntrackedValue
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from openai import APIError, APITimeoutError

from .guardrails import GUARDRAIL_BLOCKED_MESSAGE, Guardrails
from .llm import SYSTEM_PROMPT


class ChatState(MessagesState):
    pending_message: Annotated[HumanMessage, UntrackedValue]
    reply: Annotated[AIMessage, UntrackedValue]
    blocked_message_ids: Annotated[list[str], add]


def blocked_reply(message: HumanMessage) -> dict:
    reply = AIMessage(content=GUARDRAIL_BLOCKED_MESSAGE)
    if message.id is not None:
        return {"reply": reply, "blocked_message_ids": [message.id]}
    return {"reply": reply}


def build_graph(
    model, checkpointer: InMemorySaver | None = None, *,
    catalog_tool: BaseTool | None = None, currency: str | None = None,
    guardrails: Guardrails | None = None,
):
    tool_model = model.bind_tools([catalog_tool], parallel_tool_calls=False) if catalog_tool else model
    prompt = SYSTEM_PROMPT
    if currency:
        prompt += f"\nThe catalog currency is {currency}. Clarify any budget stated in a different currency."

    async def assistant(state: ChatState):
        pending = state["pending_message"]
        if guardrails is not None and await guardrails.blocks_input(pending.text):
            return blocked_reply(pending)
        messages = [
            SystemMessage(content=prompt),
            *state.get("messages", []),
            pending,
        ]
        reply = await tool_model.ainvoke(messages)
        if catalog_tool and reply.tool_calls:
            results = []
            products = {}
            for call in reply.tool_calls:
                if call["name"] == catalog_tool.name:
                    result = await catalog_tool.ainvoke(call)
                    results.append(result)
                    for product in result.artifact or []:
                        products.setdefault(product["id"], product)
                else:
                    results.append(ToolMessage("Unknown catalog tool.", tool_call_id=call["id"]))
            final = await model.ainvoke([*messages, reply, *results])
            reply = AIMessage(
                id=final.id,
                content=reply.text + final.text,
                response_metadata={"catalog_products": list(products.values())[:CHAT_PRODUCT_LIMIT]},
            )
        if guardrails is not None and await guardrails.blocks_output(reply.text):
            return blocked_reply(pending)
        if not reply.text.strip():
            return {"reply": reply}
        return {"reply": reply, "messages": [pending, reply]}

    # LangGraph accepts this TypedDict, but ty cannot match its state protocol.
    graph = StateGraph(ChatState)  # ty: ignore[invalid-argument-type]
    graph.add_node("assistant", assistant)
    graph.add_edge(START, "assistant")
    graph.add_edge("assistant", END)
    return graph.compile(checkpointer=checkpointer)


async def cached_reply(graph, config: RunnableConfig | None, message: HumanMessage) -> AIMessage | None:
    if config is None or message.id is None:
        return None
    state = await graph.aget_state(config)
    if message.id in state.values.get("blocked_message_ids", []):
        return AIMessage(content=GUARDRAIL_BLOCKED_MESSAGE)
    history = state.values.get("messages", [])
    for question, reply in zip(history[::2], history[1::2]):
        if question.id == message.id:
            return reply
    return None


async def run_reply(
    graph, message: HumanMessage, model_name: str, config: RunnableConfig | None = None,
    *, cached: AIMessage | None,
) -> AIMessage:
    with logfire.span("Run assistant graph", model=model_name) as span:
        try:
            reply = cached
            if reply is None:
                state = await graph.ainvoke({"pending_message": message}, config)
                reply = state["reply"]
        except (APITimeoutError, TimeoutError) as exc:
            span.set_attribute("outcome", "timeout")
            error = exc
        except APIError as exc:
            span.set_attribute("outcome", "provider_error")
            error = exc
        else:
            span.set_attribute("outcome", "success")
            return reply
        span.set_level("error")
    # Let the HTTP layer map provider failures outside the tracing span.
    raise error


async def stream_reply(
    graph, message: HumanMessage, model_name: str, config: RunnableConfig | None = None,
    *, cached: AIMessage | None,
) -> AsyncGenerator[dict]:
    with logfire.span("Stream assistant graph", model=model_name) as span:
        try:
            reply = cached
            if reply is None:
                state = await graph.ainvoke({"pending_message": message}, config)
                reply = state["reply"]
            if reply.text.strip():
                yield {"type": "delta", "text": reply.text}
            if products := reply.response_metadata.get("catalog_products"):
                yield {"type": "products", "products": products}
        except (APITimeoutError, TimeoutError) as exc:
            span.set_attribute("outcome", "timeout")
            error = exc
        except APIError as exc:
            span.set_attribute("outcome", "provider_error")
            error = exc
        else:
            span.set_attribute("outcome", "success")
            return
    raise error
