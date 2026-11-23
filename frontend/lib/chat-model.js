const streamType = "application/x-ndjson";

function chatQuota(response) {
  const customerId = response.headers.get("X-Chat-Customer-Id");
  const supportEmail = response.headers.get("X-Chat-Support-Email");
  const remaining = response.headers.get("X-Chat-Messages-Remaining");
  if (customerId && supportEmail && remaining !== null) {
    return { customerId, supportEmail, remaining: Number(remaining) };
  }
  return null;
}

export async function checkChatQuota(signal) {
  const request = () => fetch("/api/chat/session", { method: "POST", signal });
  // Serialize initial cookie issuance when the panel is opened in multiple tabs.
  const response = navigator.locks
    ? await navigator.locks.request("shopping-chat-session", { signal }, request)
    : await request();
  const quota = response.ok && chatQuota(response);
  if (!quota) throw new Error("Could not check your chat allowance. Try again.");
  return quota;
}

export function createChatModel(onQuota) {
  let threadId;

  async function* run({ messages, abortSignal }) {
    const latest = messages.findLast(({ role }) => role === "user");
    const message = latest?.content
      .filter(({ type }) => type === "text")
      .map(({ text }) => text)
      .join("\n");

    let reader;
    try {
      threadId ??= crypto.randomUUID();
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: streamType },
        body: JSON.stringify({ message, thread_id: threadId, message_id: latest?.id }),
        signal: abortSignal,
      });

      const quota = chatQuota(response);
      if (quota) onQuota(quota);
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        if (response.status === 429 && quota?.remaining === 0) throw new Error("Chat limit reached.");
        throw new Error(data?.detail || "The assistant could not answer. Try again.");
      }
      if (!response.body || response.headers.get("content-type")?.split(";")[0] !== streamType) {
        throw new Error("The assistant returned an invalid stream.");
      }

      reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      let text = "";
      let products = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) throw new Error("The reply was interrupted. Try again.");

        const lines = (buffer + value).split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "error") throw new Error(event.detail);
          if (event.type === "products" && Array.isArray(event.products)) {
            products = event.products;
          }
          if (event.type === "done") {
            if (!text.trim()) throw new Error("The assistant returned an empty reply. Try again.");
            if (products.length) {
              yield { content: [{ type: "text", text }, { type: "data", name: "products", data: products }] };
            }
            return;
          }
          if (event.type === "delta" && typeof event.text === "string") {
            text += event.text;
            yield { content: [{ type: "text", text }] };
          }
        }
      }
    } catch (error) {
      if (abortSignal.aborted) return;
      if (error instanceof TypeError || error instanceof SyntaxError) {
        throw new Error("The reply was interrupted. Try again.", { cause: error });
      }
      throw error;
    } finally {
      if (reader) {
        await reader.cancel().catch(() => {});
        reader.releaseLock();
      }
    }
  }

  return { run };
}
