import { useEffect, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "../../api/client";
import type { ProjectHealth } from "../../types";
import { WorkspaceCard } from "./shared";

export function HealthOverview({ sessionId }: { sessionId: string }) {
  const [health, setHealth] = useState<ProjectHealth | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const data = await api.getProjectHealth(sessionId);
      setHealth(data);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function handleConsistencyCheck() {
    setChecking(true);
    setCheckResult(null);
    try {
      const result = await api.runConsistencyCheck(sessionId);
      setCheckResult(
        result.findings_count === 0
          ? "No contradictions found."
          : `Found ${result.findings_count} issue${result.findings_count === 1 ? "" : "s"} - see the Issues tab.`,
      );
      await refresh();
    } finally {
      setChecking(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-ink-faint">Loading project health…</p>;
  }
  if (!health) {
    return <p className="text-sm text-ink-faint">Health data isn't available yet.</p>;
  }

  return (
    <div className="space-y-4">
      <WorkspaceCard
        title="Requirement coverage"
        action={
          <button
            onClick={refresh}
            title="Refresh"
            className="rounded-sm p-1 text-ink-faint hover:bg-paper hover:text-ink"
          >
            <RefreshCw size={14} />
          </button>
        }
      >
        <div className="flex items-baseline gap-2">
          <span className="font-display text-3xl text-ink">{health.requirements_coverage_pct}%</span>
          <span className="text-sm text-ink-muted">of {health.requirements_total} requirements covered</span>
        </div>
        <div className="mt-3 flex gap-4 text-sm text-ink-muted">
          {Object.entries(health.requirements_by_status).map(([status, count]) => (
            <span key={status}>
              {count} {status}
            </span>
          ))}
        </div>
      </WorkspaceCard>

      <WorkspaceCard title="Open issues">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-3xl text-ink">{health.open_issues_total}</span>
          <span className="text-sm text-ink-muted">open</span>
        </div>
        <div className="mt-3 flex gap-4 text-sm text-ink-muted">
          {Object.entries(health.open_issues_by_severity).map(([severity, count]) => (
            <span key={severity}>
              {count} {severity}
            </span>
          ))}
        </div>
      </WorkspaceCard>

      <WorkspaceCard title="Consistency check">
        <p className="mb-3 text-sm text-ink-muted">
          Runs deterministic checks across requirements and solution decisions - ERP system mismatches,
          conflicting decisions, and customizations without a stated rationale.
        </p>
        <button
          onClick={handleConsistencyCheck}
          disabled={checking}
          className="flex items-center gap-2 rounded-md bg-accent px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
        >
          <ShieldCheck size={15} />
          {checking ? "Checking…" : "Run consistency check"}
        </button>
        {checkResult && <p className="mt-2 text-sm text-ink-muted">{checkResult}</p>}
      </WorkspaceCard>
    </div>
  );
}
