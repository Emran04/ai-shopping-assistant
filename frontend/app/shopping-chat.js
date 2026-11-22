"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ActionBarPrimitive,
  AssistantModalPrimitive,
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useLocalRuntime,
} from "@assistant-ui/react";
import { checkChatQuota, createChatModel } from "../lib/chat-model";
import { CatalogProductCard } from "./catalog/catalog-product-card";

const suggestions = [
  ["Browse T-shirts", "Show me the T-shirts you have in stock."],
  ["Find my size", "Do you have women's outerwear in medium?"],
  ["Shop for kids", "Show me clothing available for kids."],
];

function AssistantText({ text }) {
  const productLink = /\[([^\]\n]+)\]\((\/catalog\/[a-z0-9]+(?:-[a-z0-9]+)*)\)/g;
  const parts = [];
  let end = 0;
  for (const match of text.matchAll(productLink)) {
    parts.push(text.slice(end, match.index), <Link key={match.index} href={match[2]}>{match[1]}</Link>);
    end = match.index + match[0].length;
  }
  return <span className="assistant-message-text">{parts}{text.slice(end)}</span>;
}

function AssistantProducts({ data: products }) {
  return (
    <ul className="catalog-grid chat-product-grid" aria-label="Matching products">
      {products.map((product) => (
        <li key={product.id}><CatalogProductCard product={product} /></li>
      ))}
    </ul>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="message user-message">
      <span className="sr-only">You: </span>
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage({ canSend }) {
  return (
    <MessagePrimitive.Root className="message assistant-message">
      <span className="sr-only">Assistant: </span>
      <AuiIf condition={({ message }) => message.status?.type === "running" && !message.parts.length}>
        <span className="pending" role="status">Waiting for a reply…</span>
      </AuiIf>
      <MessagePrimitive.Parts components={{ Text: AssistantText, data: { by_name: { products: AssistantProducts } } }} />
      <MessagePrimitive.Error>
        <ErrorPrimitive.Root className="error">
          <ErrorPrimitive.Message />
        </ErrorPrimitive.Root>
        {canSend && (
          <ActionBarPrimitive.Root className="message-actions">
            <ActionBarPrimitive.Reload className="retry">Retry</ActionBarPrimitive.Reload>
          </ActionBarPrimitive.Root>
        )}
      </MessagePrimitive.Error>
    </MessagePrimitive.Root>
  );
}

function ShoppingThread({ quota, checking, sessionError, onCheckAgain }) {
  const limited = quota?.remaining === 0;
  const canSend = Boolean(quota && !limited && !checking);

  return (
    <ThreadPrimitive.Root className="chat-thread">
      <ThreadPrimitive.Viewport
        className="chat-viewport"
        turnAnchor="top"
        scrollToBottomOnInitialize={false}
        role="log"
        aria-label="Chat messages"
        tabIndex={0}
      >
        <AuiIf condition={({ thread }) => thread.isEmpty && canSend}>
          <div className="suggestions">
            <p>Try a question</p>
            <div className="suggestion-list">
              {suggestions.map(([label, question]) => (
                <ThreadPrimitive.Suggestion key={label} prompt={question}>
                  {label} <span aria-hidden="true">↗</span>
                </ThreadPrimitive.Suggestion>
              ))}
            </div>
          </div>
        </AuiIf>
        <ThreadPrimitive.Messages>
          {({ message }) => message.role === "user" ? <UserMessage /> : <AssistantMessage canSend={canSend} />}
        </ThreadPrimitive.Messages>
      </ThreadPrimitive.Viewport>

      {limited && (
        <aside className="chat-notice" aria-label="Chat limit">
          <div role="status">
            <strong>You’ve reached your chat limit.</strong>
            <p>To reset it, call customer care at <a href={`tel:${quota.supportPhone}`}>{quota.supportPhone}</a> and share this reference.</p>
            <code>{quota.customerId}</code>
          </div>
          <button type="button" className="retry" onClick={onCheckAgain} disabled={checking}>Check again</button>
          {sessionError && <p className="error" role="alert">{sessionError}</p>}
        </aside>
      )}
      {!quota && (
        <div className="chat-notice">
          {sessionError ? (
            <>
              <p className="error" role="alert">{sessionError}</p>
              <button type="button" className="retry" onClick={onCheckAgain} disabled={checking}>Retry</button>
            </>
          ) : <p className="pending" role="status">Connecting to chat…</p>}
        </div>
      )}
      {quota && !limited && sessionError && <p className="chat-notice error" role="alert">{sessionError}</p>}
      <AuiIf condition={({ thread }) => Boolean(quota && !limited) || thread.isRunning}>
        <ComposerPrimitive.Root className="composer">
          <ComposerPrimitive.Input
            aria-label="Your shopping question"
            autoFocus
            disabled={!canSend}
            placeholder="Ask a shopping question…"
            rows={1}
          />
          <AuiIf condition={({ thread }) => thread.isRunning}>
            <ComposerPrimitive.Cancel className="send">Stop</ComposerPrimitive.Cancel>
          </AuiIf>
          <AuiIf condition={({ thread }) => !thread.isRunning}>
            <ComposerPrimitive.Send className="send" disabled={!canSend}>Send <span aria-hidden="true">↑</span></ComposerPrimitive.Send>
          </AuiIf>
        </ComposerPrimitive.Root>
      </AuiIf>
    </ThreadPrimitive.Root>
  );
}

export function ShoppingChat() {
  const [open, setOpen] = useState(false);
  const [quota, setQuota] = useState(null);
  const [checking, setChecking] = useState(false);
  const [sessionError, setSessionError] = useState("");
  const [checkAttempt, setCheckAttempt] = useState(0);
  const messageStatusVersion = useRef(0);
  const [chatModel] = useState(() => createChatModel((updatedQuota) => {
    messageStatusVersion.current += 1;
    setQuota(updatedQuota);
    setSessionError("");
  }));
  const runtime = useLocalRuntime(chatModel);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const statusVersion = messageStatusVersion.current;
    setChecking(true);
    setSessionError("");
    checkChatQuota(controller.signal).then((updatedQuota) => {
      if (!controller.signal.aborted && statusVersion === messageStatusVersion.current) setQuota(updatedQuota);
    }).catch(() => {
      if (!controller.signal.aborted && statusVersion === messageStatusVersion.current) {
        setSessionError("Could not check your chat allowance. Try again.");
      }
    }).finally(() => {
      if (!controller.signal.aborted) setChecking(false);
    });
    return () => controller.abort();
  }, [open, checkAttempt]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <AssistantModalPrimitive.Root open={open} onOpenChange={setOpen}>
        <AssistantModalPrimitive.Anchor className="chat-anchor">
          <AssistantModalPrimitive.Trigger className="chat-launcher">
            <span aria-hidden="true">{open ? "×" : "↗"}</span>
            {open ? "Close chat" : "Shopping chat"}
          </AssistantModalPrimitive.Trigger>
        </AssistantModalPrimitive.Anchor>
        <AssistantModalPrimitive.Content className="chat-panel" sideOffset={12} collisionPadding={12} aria-labelledby="chat-title">
          <div className="chat-header">
            <h2 id="chat-title">Shopping chat</h2>
          </div>
          <ShoppingThread
            quota={quota}
            checking={checking}
            sessionError={sessionError}
            onCheckAgain={() => setCheckAttempt((attempt) => attempt + 1)}
          />
        </AssistantModalPrimitive.Content>
      </AssistantModalPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
