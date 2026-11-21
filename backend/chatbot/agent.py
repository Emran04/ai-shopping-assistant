from langgraph.graph import END, START, MessagesState, StateGraph


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
