"use client";

import { useState } from "react";
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
import { createChatModel } from "../lib/chat-model";

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
  return <span>{parts}{text.slice(end)}</span>;
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="message user-message">
      <span className="sr-only">You: </span>
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="message assistant-message">
      <span className="sr-only">Assistant: </span>
      <AuiIf condition={({ message }) => message.status?.type === "running" && !message.parts.length}>
        <span className="pending" role="status">Waiting for a reply…</span>
      </AuiIf>
      <MessagePrimitive.Parts components={{ Text: AssistantText }} />
      <MessagePrimitive.Error>
        <ErrorPrimitive.Root className="error">
          <ErrorPrimitive.Message />
        </ErrorPrimitive.Root>
        <ActionBarPrimitive.Root className="message-actions">
          <ActionBarPrimitive.Reload className="retry">Retry</ActionBarPrimitive.Reload>
        </ActionBarPrimitive.Root>
      </MessagePrimitive.Error>
    </MessagePrimitive.Root>
  );
}

function ShoppingThread() {
  return (
    <ThreadPrimitive.Root className="chat-thread">
      <ThreadPrimitive.Viewport className="chat-viewport" role="log" aria-label="Chat messages" tabIndex={0}>
        <AuiIf condition={({ thread }) => thread.isEmpty}>
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
          {({ message }) => message.role === "user" ? <UserMessage /> : <AssistantMessage />}
        </ThreadPrimitive.Messages>
      </ThreadPrimitive.Viewport>

      <ComposerPrimitive.Root className="composer">
        <ComposerPrimitive.Input
          aria-label="Your shopping question"
          autoFocus
          placeholder="Ask a shopping question…"
          rows={1}
        />
        <AuiIf condition={({ thread }) => thread.isRunning}>
          <ComposerPrimitive.Cancel className="send">Stop</ComposerPrimitive.Cancel>
        </AuiIf>
        <AuiIf condition={({ thread }) => !thread.isRunning}>
          <ComposerPrimitive.Send className="send">Send <span aria-hidden="true">↑</span></ComposerPrimitive.Send>
        </AuiIf>
      </ComposerPrimitive.Root>
    </ThreadPrimitive.Root>
  );
}

export function ShoppingChat() {
  const [chatModel] = useState(createChatModel);
  const runtime = useLocalRuntime(chatModel);
  const [open, setOpen] = useState(false);

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
          <ShoppingThread />
        </AssistantModalPrimitive.Content>
      </AssistantModalPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
