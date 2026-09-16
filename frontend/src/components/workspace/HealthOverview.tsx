import { useEffect, useState } from "react";
import { ChevronDown, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "../../api/client";
import type { CoverageGaps, ProjectHealth } from "../../types";
import { WorkspaceCard } from "./shared";

function GapList({ title, items }: { title: string; items: CoverageGaps["uncovered_requirements"] }) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;

  return (
    <div className="border-t border-border pt-3 first:border-t-0 first:pt-0">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 py-1 text-left"
      >
        <span className="text-sm text-ink">
          {items.length} {title}
        </span>
        <ChevronDown size={15} className={`shrink-0 text-ink-faint transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {items.map((req) => (
            <li key={req.id} className="text-xs text-ink-muted">
              {req.description}
              {req.priority && <span className="text-ink-faint"> ({req.priority})</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function HealthOverview({ sessionId }: { sessionId: string }) {
  const [health, setHealth] = useState<ProjectHealth | null>(null);
  const [gaps, setGaps] = useState<CoverageGaps | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const [healthData, gapsData] = await Promise.all([
        api.getProjectHealth(sessionId),
        api.getCoverageGaps(sessionId),
      ]);
      setHealth(healthData);
      setGaps(gapsData);
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
            aria-label="Refresh"
            className="rounded-md p-2 text-ink-faint hover:bg-paper hover:text-ink"
          >
            <RefreshCw size={14} />
          </button>
        }
      >
        <div className="flex items-baseline gap-2">
          <span className="font-display text-3xl text-ink">{health.requirements_coverage_pct}%</span>
          <span className="text-sm text-ink-muted">of {health.requirements_total} requirements covered</span>
        </div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-muted">
          {Object.entries(health.requirements_by_status).map(([status, count]) => (
            <span key={status}>
              {count} {status}
            </span>
          ))}
        </div>

        {gaps && (gaps.uncovered_requirements.length > 0 || gaps.untested_requirements.length > 0) && (
          <div className="mt-4 space-y-3 border-t border-border pt-3">
            <GapList title="requirements with no downstream coverage yet" items={gaps.uncovered_requirements} />
            <GapList title="requirements with no test coverage yet" items={gaps.untested_requirements} />
          </div>
        )}
      </WorkspaceCard>

      <WorkspaceCard title="Open issues">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-3xl text-ink">{health.open_issues_total}</span>
          <span className="text-sm text-ink-muted">open</span>
        </div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-muted">
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
          className="flex items-center gap-2 rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
        >
          <ShieldCheck size={15} />
          {checking ? "Checking…" : "Run consistency check"}
        </button>
        <p aria-live="polite" className="mt-2 text-sm text-ink-muted">
          {checkResult}
        </p>
      </WorkspaceCard>
    </div>
  );
}
