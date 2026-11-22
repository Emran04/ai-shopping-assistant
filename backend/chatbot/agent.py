from collections.abc import AsyncGenerator
from contextlib import aclosing

import logfire
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from openai import APIError, APITimeoutError


def build_graph(model):
    async def assistant(state: MessagesState):
        reply = await model.ainvoke(state["messages"])
        return {"messages": [reply]}

    # LangGraph accepts this TypedDict, but ty cannot match its state protocol.
    graph = StateGraph(MessagesState)  # ty: ignore[invalid-argument-type]
    graph.add_node("assistant", assistant)
    graph.add_edge(START, "assistant")
    graph.add_edge("assistant", END)
    return graph.compile()


async def run_reply(graph, message: str, model_name: str) -> str:
    with logfire.span("Run assistant graph", model=model_name) as span:
        try:
            state = await graph.ainvoke({"messages": [HumanMessage(content=message)]})
        except (APITimeoutError, TimeoutError) as exc:
            span.set_attribute("outcome", "timeout")
            error = exc
        except APIError as exc:
            span.set_attribute("outcome", "provider_error")
            error = exc
        else:
            span.set_attribute("outcome", "success")
            return state["messages"][-1].text
        span.set_level("error")
    # Let the HTTP layer map provider failures outside the tracing span.
    raise error


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
