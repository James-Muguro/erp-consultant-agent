import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Globe, Send, Square } from "lucide-react";
import { MessageBubble } from "./MessageBubble";
import { AgentActivity } from "./AgentActivity";
import { EmptyState } from "./EmptyState";
import { ProjectStartCard } from "./ProjectStartCard";
import type { ChatMessage, NextAction } from "../types";
import type { AgentActivityStep } from "../hooks/useChat";

const AUTO_SCROLL_THRESHOLD_PX = 120;

export function ChatPanel({
  sessionId,
  messages,
  activity,
  sending,
  preferWeb,
  projectStartAction,
  onSend,
  onStop,
  onRetry,
  onTogglePreferWeb,
}: {
  sessionId: string | null;
  messages: ChatMessage[];
  activity: AgentActivityStep[];
  sending: boolean;
  preferWeb: boolean;
  projectStartAction?: NextAction | null;
  onSend: (text: string, agentHint?: string) => void;
  onStop: () => void;
  onRetry: (assistantMessageId: string) => void;
  onTogglePreferWeb: () => void;
}) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const nearBottomRef = useRef(true);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    nearBottomRef.current = distance < AUTO_SCROLL_THRESHOLD_PX;
  }

  useEffect(() => {
    if (!nearBottomRef.current) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, activity]);

  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    input.style.overflowY = input.scrollHeight > 160 ? "auto" : "hidden";
  }, [draft]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!draft.trim() || sending) return;
    nearBottomRef.current = true;
    onSend(draft);
    setDraft("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function handleAction(agentHint: string, label: string) {
    if (sending) return;
    nearBottomRef.current = true;
    onSend(label, agentHint);
  }

  const showEmptyState = messages.length === 0;
  const showProjectStart = showEmptyState && projectStartAction != null;
  const latestAssistantId = [...messages]
    .reverse()
    .find((m) => m.role === "assistant")?.id;

  return (
    <div className="flex h-full flex-1 flex-col">
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto">
        {showProjectStart ? (
          <ProjectStartCard
            action={projectStartAction!}
            onStart={handleAction}
            disabled={sending}
          />
        ) : showEmptyState ? (
          <EmptyState
            hasSession={sessionId != null}
            onPick={(text) => onSend(text)}
          />
        ) : (
          <div
            role="log"
            aria-label="Conversation"
            className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-5 md:gap-4 md:px-6 md:py-6"
          >
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                sessionId={sessionId}
                onAction={handleAction}
                onRetry={onRetry}
                isLatest={m.id === latestAssistantId}
              />
            ))}
            {sending && activity.length > 0 && <AgentActivity steps={activity} />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="border-t border-border bg-surface px-3 py-3 md:px-6 md:py-4">
        <div className="mx-auto max-w-3xl">
          <div className="mb-2 flex items-center gap-2">
            <button
              type="button"
              onClick={onTogglePreferWeb}
              aria-pressed={preferWeb}
              title={
                preferWeb
                  ? "Web search is on. Click to answer from the knowledge base only."
                  : "Web search is off. Click to include web sources in answers."
              }
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                preferWeb
                  ? "border-accent bg-accent-soft text-accent-strong"
                  : "border-border-strong bg-paper text-ink-muted hover:border-accent hover:text-accent"
              }`}
            >
              <Globe size={12} aria-hidden="true" />
              Web search {preferWeb ? "on" : "off"}
            </button>
          </div>
          <form onSubmit={submit} className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question, or describe what you need next…"
              aria-label="Message"
              rows={1}
              className="max-h-40 flex-1 resize-none overflow-y-hidden rounded-md border border-border-strong bg-paper px-3 py-2.5 text-sm text-ink outline-none focus:border-accent"
            />
            {sending ? (
              <button
                type="button"
                onClick={onStop}
                className="flex shrink-0 items-center gap-1.5 rounded-md border border-border-strong bg-surface px-3 py-2.5 text-sm text-ink-muted transition-colors hover:border-danger hover:text-danger"
              >
                <Square size={14} />
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!draft.trim()}
                className="flex shrink-0 items-center gap-1.5 rounded-md bg-accent px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-40"
              >
                <Send size={14} />
                Send
              </button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}