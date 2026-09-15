import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { ProjectIssue } from "../../types";
import { EmptyRow, SeverityBadge } from "./shared";

export function IssuesList({ sessionId }: { sessionId: string }) {
  const [issues, setIssues] = useState<ProjectIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    setLoading(true);
    api
      .getIssues(sessionId, showAll ? null : "open")
      .then(({ issues }) => setIssues(issues))
      .finally(() => setLoading(false));
  }, [sessionId, showAll]);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-sm font-medium text-ink-muted">
          {showAll ? "All issues" : "Open issues"}
        </h4>
        <button
          onClick={() => setShowAll((v) => !v)}
          className="text-xs text-accent-strong hover:underline"
        >
          {showAll ? "Show open only" : "Show all"}
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-ink-faint">Loading issues…</p>
      ) : issues.length === 0 ? (
        <EmptyRow label="No issues found. Run a consistency check from the Overview tab to look for contradictions." />
      ) : (
        <ul className="space-y-2">
          {issues.map((issue) => (
            <li key={issue.id} className="rounded-md border border-border bg-surface p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink">{issue.description}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-ink-faint">
                    <span>{issue.issue_type.replace(/_/g, " ")}</span>
                    <span>{issue.status}</span>
                    {issue.related_object_type && <span>{issue.related_object_type.replace(/_/g, " ")}</span>}
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
