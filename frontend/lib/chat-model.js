const streamType = "application/x-ndjson";

export const chatModel = {
  async *run({ messages, abortSignal }) {
    const latest = messages.findLast(({ role }) => role === "user");
    const message = latest?.content
      .filter(({ type }) => type === "text")
      .map(({ text }) => text)
      .join("\n");

    let reader;
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: streamType },
        body: JSON.stringify({ message }),
        signal: abortSignal,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail || "The assistant could not answer. Try again.");
      }
      if (!response.body || response.headers.get("content-type")?.split(";")[0] !== streamType) {
        throw new Error("The assistant returned an invalid stream.");
      }

      reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      let text = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) throw new Error("The reply was interrupted. Try again.");

        const lines = (buffer + value).split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "error") throw new Error(event.detail);
          if (event.type === "done") {
            if (!text.trim()) throw new Error("The assistant returned an empty reply. Try again.");
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
  },
};
