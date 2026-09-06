import ReactMarkdown from "react-markdown";
import { FileText } from "lucide-react";
import type { ChatMessage } from "../types";
import { api } from "../api/client";

export function MessageBubble({
  message,
  sessionId,
}: {
  message: ChatMessage;
  sessionId: string | null;
}) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[75ch] rounded-md px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? "bg-accent text-white"
            : message.error
              ? "border border-danger-soft bg-danger-soft text-danger"
              : "border border-border bg-surface text-ink"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.text}</p>
        ) : (
          <div className="prose-chat">
            <ReactMarkdown>{message.text || (message.isStreaming ? "…" : "")}</ReactMarkdown>
          </div>
        )}

        {message.documents && message.documents.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2 border-t border-border pt-2">
            {message.documents.map((doc) => (
              <button
                key={doc.filename}
                onClick={() => sessionId && api.downloadDocument(sessionId, doc.filename)}
                className="flex items-center gap-1.5 rounded-md border border-border bg-paper px-2 py-1 text-xs text-ink-muted transition-colors hover:border-accent hover:text-accent"
              >
                <FileText size={12} />
                {doc.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
