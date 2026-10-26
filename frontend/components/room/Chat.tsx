"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";

export function Chat({ messages, thinking }: { messages: ChatMessage[]; thinking: boolean }) {
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, thinking]);

  return (
    <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-4 py-5" aria-live="polite">
      {messages.map((message) => {
        const mine = message.sender_role !== "ai";
        return (
          <div key={message.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
            <p
              className={`max-w-[85%] rounded-3xl px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap ${
                mine ? "rounded-br-lg bg-teal text-card" : "rounded-bl-lg bg-card text-ink shadow-[0_1px_0_rgba(36,28,22,0.08)]"
              }`}
            >
              {message.content}
            </p>
          </div>
        );
      })}
      {thinking ? (
        <div className="flex justify-start" aria-label="Mediator is replying">
          <span className="flex gap-1 rounded-3xl rounded-bl-lg bg-card px-4 py-4 shadow-[0_1px_0_rgba(36,28,22,0.08)]">
            {[0, 150, 300].map((delay) => (
              <span
                key={delay}
                className="h-2 w-2 animate-bounce rounded-full bg-muted/60"
                style={{ animationDelay: `${delay}ms` }}
              />
            ))}
          </span>
        </div>
      ) : null}
    </div>
  );
}
