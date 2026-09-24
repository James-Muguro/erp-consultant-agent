import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { ProjectIssue } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow, SeverityBadge } from "./shared";

/**
 * Open issues for a project.
 *
 * There is intentionally no "show all" toggle. The backend endpoint
 * (`GET /api/projects/{id}/issues`) applies a default status of "open"
 * when the query parameter is omitted, and does not currently support
 * fetching across all statuses.
 */
export function IssuesList({ sessionId }: { sessionId: string }) {
  const [issues, setIssues] = useState<ProjectIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { issues: items } = await api.getIssues(sessionId, "open");
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

  const handleRetry = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    setReloadToken((n) => n + 1);
  }, []);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-sm font-medium text-ink-muted">Open issues</h4>
      </div>

      {loading ? (
        <LoadingRow label="Loading issues…" />
      ) : loadError ? (
        <ErrorRow message={loadError} onRetry={handleRetry} />
      ) : issues.length === 0 ? (
        <EmptyRow label="No issues found. Run a consistency check from the Overview tab to look for contradictions." />
      ) : (
        <ul className="space-y-2">
          {issues.map((issue) => (
            <li
              key={issue.id}
              className="rounded-md border border-border bg-surface p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink">{issue.description}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-ink-faint">
                    <span>{issue.issue_type.replace(/_/g, " ")}</span>
                    <span>{issue.status}</span>
                    {issue.related_object_type && (
                      <span>{issue.related_object_type.replace(/_/g, " ")}</span>
                    )}
                  </div>
                </div>
                <SeverityBadge severity={issue.severity} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}