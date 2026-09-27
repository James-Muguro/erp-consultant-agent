import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { useCapabilities } from "../../auth/useCapabilities";
import type { ProjectIssue } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow, SeverityBadge } from "./shared";
const ACTIVE_STATUSES =
  "open,developer_marked_complete,reopened_with_feedback";

const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  developer_marked_complete: "Awaiting confirmation",
  reopened_with_feedback: "Reopened with feedback",
  consultant_confirmed_resolved: "Resolved",
};

export function IssuesList({ sessionId }: { sessionId: string }) {
  const capabilities = useCapabilities();
  const canComplete = capabilities.can("issues:write");
  const canReview = capabilities.can("reviews:submit");

  const [issues, setIssues] = useState<ProjectIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [reopeningFor, setReopeningFor] = useState<string | null>(null);
  const [reopenNote, setReopenNote] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

  const [searchParams] = useSearchParams();
  const focusRaw = searchParams.get("focus");
  const focusId = focusRaw?.startsWith("issue:")
    ? focusRaw.slice("issue:".length)
    : null;
  const rowRefs = useRef<Record<string, HTMLLIElement | null>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { issues: items } = await api.getIssues(
          sessionId, ACTIVE_STATUSES,
        );
        if (cancelled) return;
        setIssues(items);
        setLoadError(null);
      } catch (err) {
        if (cancelled) return;
        setIssues([]);
        setLoadError(
          err instanceof Error ? err.message : "Could not load issues.",
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, reloadToken]);

  useEffect(() => {
    if (!focusId || loading) return;
    const el = rowRefs.current[focusId];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [focusId, loading, issues]);

  const handleRetry = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    setReloadToken((n) => n + 1);
  }, []);

  async function act(
    issueId: string,
    kind: "complete" | "confirm" | "reopen",
    note?: string,
  ) {
    setActingOn(issueId);
    setActionError(null);
    try {
      if (kind === "complete") {
        await api.markIssueDeveloperComplete(sessionId, issueId);
      } else if (kind === "confirm") {
        await api.confirmIssueResolved(sessionId, issueId);
      } else {
        await api.reopenIssue(sessionId, issueId, note ?? "");
      }
      setReopeningFor(null);
      setReopenNote("");
      setReloadToken((n) => n + 1);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Could not save the action.",
      );
    } finally {
      setActingOn(null);
    }
  }

  if (loading) return <LoadingRow label="Loading issues…" />;
  if (loadError) return <ErrorRow message={loadError} onRetry={handleRetry} />;
  if (issues.length === 0) {
    return (
      <EmptyRow label="No active issues. Run a consistency check from the Overview tab to look for contradictions." />
    );
  }

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-ink-muted">Active issues</h4>

      {actionError && (
        <p
          role="alert"
          className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          {actionError}
        </p>
      )}

      <ul className="space-y-2">
        {issues.map((issue) => {
          const pending = actingOn === issue.id;
          const showComplete =
            canComplete &&
            (issue.status === "open" ||
              issue.status === "reopened_with_feedback");
          const showReview =
            canReview && issue.status === "developer_marked_complete";
          return (
                  <li
                    key={issue.id}
                    ref={(el) => {
                      rowRefs.current[issue.id] = el;
                    }}
                    className={`rounded-md border bg-surface p-3 ${
                      issue.id === focusId
                        ? "border-accent ring-1 ring-accent"
                        : "border-border"
                    } ${pending ? "opacity-70" : ""}`}
                    aria-busy={pending}
                  >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink">{issue.description}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-ink-faint">
                    <span>{issue.issue_type.replace(/_/g, " ")}</span>
                    <span>
                      {STATUS_LABEL[issue.status] ?? issue.status}
                    </span>
                    {issue.related_object_type && (
                      <span>
                        {issue.related_object_type.replace(/_/g, " ")}
                      </span>
                    )}
                  </div>
                  {issue.status === "reopened_with_feedback" &&
                    issue.reopen_note && (
                      <p className="mt-2 rounded-md bg-warning-soft px-2 py-1 text-xs text-ink">
                        Reopened: {issue.reopen_note}
                        {issue.reopen_at && (
                          <span className="ml-1 text-ink-faint">
                            ({new Date(issue.reopen_at).toLocaleString()})
                          </span>
                        )}
                      </p>
                    )}
                  {issue.completion_count !== undefined &&
                    issue.completion_count > 0 && (
                      <p className="mt-1 text-xs text-ink-faint">
                        Completion attempts: {issue.completion_count}
                      </p>
                    )}
                </div>
                <SeverityBadge severity={issue.severity} />
              </div>

              {(showComplete || showReview) && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {showComplete && (
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() => act(issue.id, "complete")}
                      className="rounded-md border border-accent px-2 py-1 text-xs text-accent-strong disabled:opacity-50"
                    >
                      {pending ? "Saving…" : "Mark complete"}
                    </button>
                  )}
                  {showReview && (
                    <>
                      <button
                        type="button"
                        disabled={pending}
                        onClick={() => act(issue.id, "confirm")}
                        className="rounded-md border border-accent px-2 py-1 text-xs text-accent-strong disabled:opacity-50"
                      >
                        Confirm resolved
                      </button>
                      <button
                        type="button"
                        disabled={pending}
                        onClick={() => {
                          setReopeningFor(issue.id);
                          setReopenNote("");
                        }}
                        className="rounded-md border border-border px-2 py-1 text-xs text-ink-muted hover:border-danger hover:text-danger disabled:opacity-50"
                      >
                        Reopen
                      </button>
                    </>
                  )}
                </div>
              )}

              {reopeningFor === issue.id && (
                <div className="mt-3 space-y-2 rounded-md border border-border bg-paper p-2">
                  <textarea
                    value={reopenNote}
                    onChange={(e) => setReopenNote(e.target.value)}
                    rows={2}
                    placeholder="Explain what still needs to be done…"
                    className="w-full rounded-md border border-border bg-surface p-2 text-xs"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={pending || !reopenNote.trim()}
                      onClick={() => act(issue.id, "reopen", reopenNote.trim())}
                      className="rounded-md bg-danger-soft px-2 py-1 text-xs text-danger disabled:opacity-50"
                    >
                      Send back to developer
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setReopeningFor(null);
                        setReopenNote("");
                      }}
                      className="rounded-md border border-border px-2 py-1 text-xs text-ink-muted"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}