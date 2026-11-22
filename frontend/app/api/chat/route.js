import { chatBackendRequest, chatResponseHeaders } from "../../../lib/chat-api";

const streamType = "application/x-ndjson";

export async function POST(request) {
  const body = await request.json().catch(() => null);
  const message = typeof body?.message === "string" ? body.message.trim() : "";

  if (!message) {
    return Response.json({ detail: "Enter a question first." }, { status: 400 });
  }

  const streaming = request.headers.get("accept") === streamType;
  try {
    const path = streaming ? "/chat/stream" : "/chat";
    const response = await chatBackendRequest(request, path, streaming ? 120_000 : 35_000, {
      message, thread_id: body.thread_id, message_id: body.message_id,
    });
    const headers = chatResponseHeaders(request, response);

    if (streaming && response.ok) {
      if (response.body && response.headers.get("content-type")?.split(";")[0] === streamType) {
        headers.set("Content-Type", streamType);
        headers.set("Cache-Control", "no-store, no-transform");
        headers.set("X-Accel-Buffering", "no");
        return new Response(response.body, { headers });
      }
      await response.body?.cancel();
      return Response.json({ detail: "The assistant returned an invalid stream." }, { status: 502, headers });
    }

    const data = await response.json();

    if (!response.ok) {
      const detail = typeof data?.detail === "string"
        ? data.detail
        : "The assistant could not answer. Try again.";
      return Response.json({ detail }, { status: response.status, headers });
    }

    if (typeof data?.reply === "string") {
      const reply = { reply: data.reply };
      if (Array.isArray(data.products)) reply.products = data.products;
      return Response.json(reply, { headers });
    }
  } catch (error) {
    if (error.name === "TimeoutError") {
      return Response.json({ detail: "The assistant took too long to reply." }, { status: 504 });
    }
  }

  return Response.json({ detail: "Could not reach the FastAPI assistant." }, { status: 502 });
}
