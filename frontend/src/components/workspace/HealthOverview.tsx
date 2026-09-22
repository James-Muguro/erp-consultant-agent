import { useCallback, useEffect, useState } from "react";
import { ChevronDown, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "../../api/client";
import type { CoverageGaps, ProjectHealth } from "../../types";
import { WorkspaceCard } from "./shared";

/** Render a status-count map defensively. The backend contract is
 * `Record<string, number>`, but a shape mismatch should degrade to a
 * readable label rather than "undefined draft" or "[object Object]". */
function renderCounts(counts: Record<string, number>): string[] {
  const out: string[] = [];
  for (const [label, raw] of Object.entries(counts)) {
    const n = typeof raw === "number" ? raw : Number(raw);
    if (!Number.isFinite(n)) continue;
    out.push(`${n} ${label}`);
  }
  return out;
}

function GapList({
  title,
  items,
}: {
  title: string;
  items: CoverageGaps["uncovered_requirements"];
}) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;

  return (
    <div className="border-t border-border pt-3 first:border-t-0 first:pt-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 py-1 text-left"
      >
        <span className="text-sm text-ink">
          {items.length} {title}
        </span>
        <ChevronDown
          size={15}
          className={`shrink-0 text-ink-faint transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {items.map((req) => (
            <li key={req.id} className="text-xs text-ink-muted">
              {req.description}
              {req.priority && (
                <span className="text-ink-faint"> ({req.priority})</span>
              )}
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
  const [gapsError, setGapsError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<string | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoadError(null);
    setGapsError(null);
    setLoading(true);
    const [healthResult, gapsResult] = await Promise.allSettled([
      api.getProjectHealth(sessionId),
      api.getCoverageGaps(sessionId),
    ]);
    if (healthResult.status === "fulfilled") {
      setHealth(healthResult.value);
    } else {
      setHealth(null);
      setLoadError(
        healthResult.reason instanceof Error
          ? healthResult.reason.message
          : "Could not load project health.",
      );
    }
    if (gapsResult.status === "fulfilled") {
      setGaps(gapsResult.value);
    } else {
      setGaps(null);
      setGapsError(
        gapsResult.reason instanceof Error
          ? gapsResult.reason.message
          : "Could not load coverage gaps.",
      );
    }
    setLoading(false);
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (cancelled) return;
      await refresh();
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  async function handleConsistencyCheck() {
    setChecking(true);
    setCheckResult(null);
    setCheckError(null);
    try {
      const result = await api.runConsistencyCheck(sessionId);
      setCheckResult(
        result.findings_count === 0
          ? "No contradictions found."
          : `Found ${result.findings_count} issue${result.findings_count === 1 ? "" : "s"} - see the Issues tab.`,
      );
      await refresh();
    } catch (err) {
      setCheckError(
        err instanceof Error ? err.message : "Consistency check failed.",
      );
    } finally {
      setChecking(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-ink-faint">Loading project health…</p>;
  }

  if (loadError) {
    return (
      <WorkspaceCard title="Project health">
        <p className="text-sm text-danger" role="alert">
          {loadError}
        </p>
        <button
          type="button"
          onClick={refresh}
          className="mt-3 rounded-md border border-border-strong px-3 py-1.5 text-xs text-ink-muted hover:border-accent hover:text-accent"
        >
          Retry
        </button>
      </WorkspaceCard>
    );
  }

  if (!health) {
    return <p className="text-sm text-ink-faint">Health data isn't available yet.</p>;
  }

  const coveragePct = Math.round(health.requirements_coverage_pct);
  const statusCounts = renderCounts(health.requirements_by_status);
  const severityCounts = renderCounts(health.open_issues_by_severity);

  return (
    <div className="space-y-4">
      <WorkspaceCard
        title="Requirement coverage"
        action={
          <button
            type="button"
            onClick={refresh}
            aria-label="Refresh project health"
            className="rounded-md p-2 text-ink-faint hover:bg-paper hover:text-ink"
          >
            <RefreshCw size={14} aria-hidden="true" />
          </button>
        }
      >
        <div className="flex items-baseline gap-2">
          <span className="font-display text-3xl text-ink">{coveragePct}%</span>
          <span className="text-sm text-ink-muted">
            of {health.requirements_total} requirements covered
          </span>
        </div>
        {statusCounts.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-muted">
            {statusCounts.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
        )}

        {/* Baseline presence is a first-class signal from the backend:
            an active baseline means the solution has been frozen at a
            point in time. Surfacing it here is deliberate - the field
            existed on the health response and had no consumer. */}
        <p className="mt-3 text-xs text-ink-faint">
          {health.has_active_baseline
            ? "An active solution baseline is recorded for this project."
            : "No active solution baseline yet."}
        </p>

        {gapsError && (
          <p className="mt-3 text-xs text-danger" role="alert">
            {gapsError}
          </p>
        )}

        {gaps &&
          (gaps.uncovered_requirements.length > 0 ||
            gaps.untested_requirements.length > 0) && (
            <div className="mt-4 space-y-3 border-t border-border pt-3">
              <GapList
                title="requirements with no downstream coverage yet"
                items={gaps.uncovered_requirements}
              />
              <GapList
                title="requirements with no test coverage yet"
                items={gaps.untested_requirements}
              />
            </div>
          )}
      </WorkspaceCard>

      <WorkspaceCard title="Open issues">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-3xl text-ink">
            {health.open_issues_total}
          </span>
          <span className="text-sm text-ink-muted">open</span>
        </div>
        {severityCounts.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-muted">
            {severityCounts.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
        )}
      </WorkspaceCard>

      <WorkspaceCard title="Consistency check">
        <p className="mb-3 text-sm text-ink-muted">
          Runs deterministic checks across requirements and solution decisions -
          ERP system mismatches, conflicting decisions, and customizations
          without a stated rationale. Findings appear in the Issues tab.
        </p>
        <button
          type="button"
          onClick={handleConsistencyCheck}
          disabled={checking}
          className="flex items-center gap-2 rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
        >
          <ShieldCheck size={15} aria-hidden="true" />
          {checking ? "Checking…" : "Run consistency check"}
        </button>
        {checkResult && (
          <p aria-live="polite" className="mt-2 text-sm text-ink-muted">
            {checkResult}
          </p>
        )}
        {checkError && (
          <p role="alert" className="mt-2 text-sm text-danger">
            {checkError}
          </p>
        )}
      </WorkspaceCard>
    </div>
  );
}