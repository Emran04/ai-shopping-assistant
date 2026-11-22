"use client";

import { useState } from "react";
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
  ["Compare options", "What should I compare when choosing noise-canceling headphones?"],
  ["Shop on a budget", "What should I look for in a coffee maker under $100?"],
  ["Find a gift", "Suggest a few practical gifts for someone who loves cooking."],
];

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
      <MessagePrimitive.Parts />
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
