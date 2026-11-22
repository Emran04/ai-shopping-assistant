import { chatBackendRequest, chatResponseHeaders } from "../../../../lib/chat-api";

export async function POST(request) {
  try {
    const response = await chatBackendRequest(request, "/chat/session", 10_000);
    const headers = chatResponseHeaders(request, response);
    return Response.json(await response.json(), { status: response.status, headers });
  } catch {
    return Response.json({ detail: "Could not check your chat allowance. Try again." }, { status: 502 });
  }
}
