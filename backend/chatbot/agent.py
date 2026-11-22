from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Annotated

import logfire
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.channels import UntrackedValue
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from openai import APIError, APITimeoutError

from .llm import SYSTEM_PROMPT


class ChatState(MessagesState):
    pending_message: Annotated[HumanMessage, UntrackedValue]
    reply_text: Annotated[str, UntrackedValue]


def build_graph(
    model, checkpointer: InMemorySaver | None = None, *,
    catalog_tool: BaseTool | None = None, currency: str | None = None,
):
    tool_model = model.bind_tools([catalog_tool], parallel_tool_calls=False) if catalog_tool else model
    prompt = SYSTEM_PROMPT
    if currency:
        prompt += f"\nThe catalog currency is {currency}. Clarify any budget stated in a different currency."

    async def assistant(state: ChatState):
        pending = state["pending_message"]
        messages = [
            SystemMessage(content=prompt),
            *state.get("messages", []),
            pending,
        ]
        reply = await tool_model.ainvoke(messages)
        if catalog_tool and reply.tool_calls:
            results = []
            for call in reply.tool_calls:
                if call["name"] == catalog_tool.name:
                    results.append(await catalog_tool.ainvoke(call))
                else:
                    results.append(ToolMessage("Unknown catalog tool.", tool_call_id=call["id"]))
            final = await model.ainvoke([*messages, reply, *results])
            reply = AIMessage(id=final.id, content=reply.text + final.text)
        if not reply.text.strip():
            return {"reply_text": reply.text}
        return {"reply_text": reply.text, "messages": [pending, reply]}

    # LangGraph accepts this TypedDict, but ty cannot match its state protocol.
    graph = StateGraph(ChatState)  # ty: ignore[invalid-argument-type]
    graph.add_node("assistant", assistant)
    graph.add_edge(START, "assistant")
    graph.add_edge("assistant", END)
    return graph.compile(checkpointer=checkpointer)


async def cached_reply(graph, config: RunnableConfig | None, message: HumanMessage) -> str | None:
    if config is None or message.id is None:
        return None
    state = await graph.aget_state(config)
    history = state.values.get("messages", [])
    for question, reply in zip(history[::2], history[1::2]):
        if question.id == message.id:
            return reply.text
    return None


async def run_reply(
    graph, message: HumanMessage, model_name: str, config: RunnableConfig | None = None,
) -> str:
    with logfire.span("Run assistant graph", model=model_name) as span:
        try:
            reply = await cached_reply(graph, config, message)
            if reply is None:
                state = await graph.ainvoke({"pending_message": message}, config)
                reply = state["reply_text"]
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
) -> AsyncGenerator[str]:
    with logfire.span("Stream assistant graph", model=model_name) as span:
        try:
            reply = await cached_reply(graph, config, message)
            if reply is not None:
                yield reply
                span.set_attribute("outcome", "success")
                return
            events = graph.astream(
                {"pending_message": message},
                config,
                stream_mode="messages",
                version="v2",
            )
            async with aclosing(events):
                async for event in events:
                    chunk, metadata = event["data"]
                    if metadata.get("langgraph_node") != "assistant" or not isinstance(chunk, AIMessage):
                        continue
                    if text := chunk.text:
                        yield text
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
