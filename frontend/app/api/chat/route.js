export async function POST(request) {
  const body = await request.json().catch(() => null);
  const message = typeof body?.message === "string" ? body.message.trim() : "";

  if (!message) {
    return Response.json({ detail: "Enter a question first." }, { status: 400 });
  }

  try {
    const backendUrl = process.env.FASTAPI_URL || "http://127.0.0.1:8000";
    const response = await fetch(new URL("/chat", backendUrl), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      cache: "no-store",
      signal: AbortSignal.timeout(35_000),
    });
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
