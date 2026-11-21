"use client";

import { useEffect, useRef, useState } from "react";

const suggestions = [
  {
    label: "Compare options",
    question: "What should I compare when choosing noise-canceling headphones?",
  },
  {
    label: "Shop on a budget",
    question: "What should I look for in a coffee maker under $100?",
  },
  {
    label: "Find a gift",
    question: "Suggest a few practical gifts for someone who loves cooking.",
  },
];

export default function Home() {
  const [draft, setDraft] = useState("");
  const [exchanges, setExchanges] = useState([]);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const input = useRef(null);
  const thread = useRef(null);

  useEffect(() => {
    if (thread.current) {
      thread.current.scrollTop = thread.current.scrollHeight;
    }
  }, [exchanges, pending]);

  async function sendMessage(event) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || pending) return;

    setError("");
    setPending(message);
    setDraft("");

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "The assistant could not answer. Try again.");
      }

      setExchanges((previous) => [...previous, { message, reply: data.reply }]);
    } catch (error) {
      setDraft(message);
      setError(
        error instanceof Error && error.name === "Error"
          ? error.message
          : "Could not reach the assistant. Try again.",
      );
    } finally {
      setPending("");
      input.current?.focus();
    }
  }

  function chooseSuggestion(question) {
    setDraft(question);
    setError("");
    input.current?.focus();
  }

  return (
    <div className="site-shell">
      <header className="site-header">
        <div className="wordmark">
          <span className="brand-mark" aria-hidden="true">e.</span>
          Ecomm Assistant
        </div>
      </header>

      <main className="workspace">
        <section className="intro" aria-labelledby="page-title">
          <h1 id="page-title">What are you<br className="desktop-break" /> shopping for?</h1>
          <p>Ask what to look for, compare options, or find a gift that fits your budget.</p>
        </section>

        <section className="chat" aria-labelledby="chat-title">
          <div className="chat-header">
            <h2 id="chat-title">Shopping chat</h2>
          </div>

          <div className="chat-content">
            {exchanges.length === 0 && !pending && (
              <div className="suggestions">
                <p>Try a question</p>
                <div className="suggestion-list">
                  {suggestions.map(({ label, question }) => (
                    <button key={label} type="button" onClick={() => chooseSuggestion(question)}>
                      {label} <span aria-hidden="true">↗</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div
              className="thread"
              role="log"
              aria-label="Chat messages"
              tabIndex={exchanges.length || pending ? 0 : undefined}
              ref={thread}
            >
              {exchanges.map(({ message, reply }, index) => (
                <div className="exchange" key={index}>
                  <p className="message user-message"><span className="sr-only">You: </span>{message}</p>
                  <p className="message assistant-message"><span className="sr-only">Assistant: </span>{reply}</p>
                </div>
              ))}
              {pending && (
                <div className="exchange">
                  <p className="message user-message"><span className="sr-only">You: </span>{pending}</p>
                  <p className="pending">Waiting for a reply…</p>
                </div>
              )}
            </div>
          </div>

          {error && <p className="error" role="alert">{error}</p>}

          <form className="composer" onSubmit={sendMessage}>
            <label htmlFor="question" className="sr-only">Your shopping question</label>
            <input
              id="question"
              ref={input}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              readOnly={Boolean(pending)}
              placeholder="Ask a shopping question…"
              required
            />
            <button className="send" type="submit" disabled={Boolean(pending) || !draft.trim()}>
              Send <span aria-hidden="true">↑</span>
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}
