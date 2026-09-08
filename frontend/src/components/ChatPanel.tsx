import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Send, Square } from "lucide-react";
import { MessageBubble } from "./MessageBubble";
import { AgentActivity } from "./AgentActivity";
import { EmptyState } from "./EmptyState";
import type { ChatMessage } from "../types";
import type { AgentActivityStep } from "../hooks/useChat";

export function ChatPanel({
  sessionId,
  messages,
  activity,
  sending,
  streamError,
  onSend,
  onStop,
}: {
  sessionId: string | null;
  messages: ChatMessage[];
  activity: AgentActivityStep[];
  sending: boolean;
  streamError: string | null;
  onSend: (text: string, agentHint?: string) => void;
  onStop: () => void;
}) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, activity]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!draft.trim() || sending) return;
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
    onSend(label, agentHint);
  }

  const showEmptyState = messages.length === 0;

  return (
    <div className="flex h-full flex-1 flex-col">
      <div className="flex-1 overflow-y-auto">
        {showEmptyState ? (
          <EmptyState onPick={(text) => onSend(text)} />
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-6">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} sessionId={sessionId} onAction={handleAction} />
            ))}
            {sending && activity.length > 0 && <AgentActivity steps={activity} />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="border-t border-border bg-surface px-6 py-4">
        <div className="mx-auto max-w-3xl">
          {streamError && (
            <p className="mb-2 rounded-md bg-danger-soft px-3 py-1.5 text-xs text-danger">
              {streamError}
            </p>
          )}
          <form onSubmit={submit} className="flex items-end gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question, or describe what you need next…"
              rows={1}
              className="max-h-40 flex-1 resize-none rounded-md border border-border bg-paper px-3 py-2.5 text-sm text-ink outline-none focus:border-accent"
            />
            {sending ? (
              <button
                type="button"
                onClick={onStop}
                className="flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-2.5 text-sm text-ink-muted transition-colors hover:border-danger hover:text-danger"
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