import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FileText, RefreshCw } from "lucide-react";
import type { ChatMessage, DocumentRef } from "../types";
import { api } from "../api/client";

/**
 * Renders a single conversation turn.
 *
 * Security note: `rehype-raw` was removed deliberately. It re-enabled
 * raw HTML parsing inside markdown, which turns any HTML that flows
 * through the LLM (its own output, or retrieved web content the model
 * echoed) into an XSS vector. `remark-gfm` covers tables, strikethrough,
 * task lists, and autolinks - what a consulting deliverable actually
 * needs.
 *
 * Link handling: markdown links in assistant output are always external
 * (retrieved sources, references). They are rendered with
 * target="_blank" and rel="noopener noreferrer" so following a source
 * does not replace the running SPA - which would otherwise lose the
 * user's in-progress conversation with no way back except browser back.
 */
export function MessageBubble({
  message,
  sessionId,
  onAction,
  onRetry,
  isLatest,
}: {
  message: ChatMessage;
  sessionId: string | null;
  onAction: (agentHint: string, label: string) => void;
  onRetry: (assistantMessageId: string) => void;
  isLatest: boolean;
}) {
  const isUser = message.role === "user";
  const [downloadingFilename, setDownloadingFilename] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  async function handleDownload(doc: DocumentRef) {
    if (!sessionId) return;
    setDownloadError(null);
    setDownloadingFilename(doc.filename);
    try {
      await api.downloadDocument(sessionId, doc.filename);
    } catch (err) {
      setDownloadError(
        err instanceof Error ? err.message : "Could not download document.",
      );
    } finally {
      setDownloadingFilename(null);
    }
  }

  const turnState = message.turnState;
  const isStreaming = turnState?.status === "streaming";
  const isFailed = turnState?.status === "failed";
  const failureMessage = isFailed ? turnState.error : null;

  const showNextAction =
    isLatest && !isStreaming && !isFailed && message.nextAction != null;
  const showRetry =
    isLatest && isFailed && turnState.retryable === true;

  const assistantBody =
    message.text || (isStreaming ? "…" : failureMessage ?? "");

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[88%] rounded-md px-4 py-2.5 text-sm leading-relaxed sm:max-w-[75ch] ${
          isUser
            ? "bg-accent text-white"
            : isFailed
              ? "border border-danger-soft bg-danger-soft text-danger"
              : "border border-border bg-surface text-ink"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">
            <span className="sr-only">You said: </span>
            {message.text}
          </p>
        ) : (
          <div className="prose-chat">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children, ...props }) => (
                  <a
                    {...props}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {assistantBody}
            </ReactMarkdown>
          </div>
        )}

        {message.documents && message.documents.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2 border-t border-border pt-2">
            {message.documents.map((doc) => {
              const pending = downloadingFilename === doc.filename;
              return (
                <button
                  key={doc.filename}
                  type="button"
                  onClick={() => handleDownload(doc)}
                  disabled={pending}
                  className="flex items-center gap-1.5 rounded-md border border-border-strong bg-paper px-2.5 py-1.5 text-xs text-ink-muted transition-colors hover:border-accent hover:text-accent disabled:opacity-60"
                >
                  <FileText size={12} aria-hidden="true" />
                  {pending ? `Downloading ${doc.label}…` : doc.label}
                </button>
              );
            })}
          </div>
        )}

        {downloadError && (
          <p className="mt-1.5 text-xs text-danger" role="alert">
            {downloadError}
          </p>
        )}

        {showRetry && (
          <div className="mt-2 border-t border-border pt-2">
            <button
              type="button"
              onClick={() => onRetry(message.id)}
              className="inline-flex items-center gap-1.5 rounded-md border border-danger bg-danger-soft px-3 py-1.5 text-xs font-medium text-danger transition-colors hover:bg-danger hover:text-white"
            >
              <RefreshCw size={12} aria-hidden="true" />
              Try again
            </button>
          </div>
        )}

        {showNextAction && message.nextAction && (
          <div className="mt-2 border-t border-border pt-2">
            <button
              type="button"
              onClick={() =>
                onAction(message.nextAction!.agent_hint, message.nextAction!.label)
              }
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent-strong"
            >
              {message.nextAction.label}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}