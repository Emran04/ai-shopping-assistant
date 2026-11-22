const streamType = "application/x-ndjson";

export async function POST(request) {
  const body = await request.json().catch(() => null);
  const message = typeof body?.message === "string" ? body.message.trim() : "";

  if (!message) {
    return Response.json({ detail: "Enter a question first." }, { status: 400 });
  }

  const streaming = request.headers.get("accept") === streamType;
  try {
    const backendUrl = process.env.FASTAPI_URL || "http://127.0.0.1:8000";
    const path = streaming ? "/chat/stream" : "/chat";
    const response = await fetch(new URL(path, backendUrl), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, thread_id: body.thread_id, message_id: body.message_id }),
      cache: "no-store",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(streaming ? 120_000 : 35_000)]),
    });

    if (streaming && response.ok) {
      if (response.body && response.headers.get("content-type")?.split(";")[0] === streamType) {
        return new Response(response.body, {
          headers: {
            "Content-Type": streamType,
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
          },
        });
      }
      await response.body?.cancel();
      return Response.json({ detail: "The assistant returned an invalid stream." }, { status: 502 });
    }

    const data = await response.json();

    if (!response.ok) {
      const detail = typeof data?.detail === "string"
        ? data.detail
        : "The assistant could not answer. Try again.";
      return Response.json({ detail }, { status: response.status });
    }

    if (typeof data?.reply === "string") {
      return Response.json({ reply: data.reply });
    }
  } catch (error) {
    if (error.name === "TimeoutError") {
      return Response.json({ detail: "The assistant took too long to reply." }, { status: 504 });
    }
  }

  return Response.json({ detail: "Could not reach the FastAPI assistant." }, { status: 502 });
}
