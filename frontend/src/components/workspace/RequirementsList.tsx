import { useCallback, useEffect, useState } from "react";
import { Check, X } from "lucide-react";
import { api } from "../../api/client";
import type { RequirementItem } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow, StatusBadge } from "./shared";

/**
 * Requirements tab. Loads requirements, groups them by category, and
 * offers approve/reject on drafts.
 *
 * The fetch lives inside the effect so the setState calls are provably
 * downstream of an await, not synchronous with the effect body. A
 * reloadToken drives retry and post-action refetch; the per-run
 * `cancelled` flag discards in-flight responses when the effect re-runs.
 */
export function RequirementsList({ sessionId }: { sessionId: string }) {
  const [requirements, setRequirements] = useState<RequirementItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { requirements: items } = await api.getRequirements(sessionId);
        if (cancelled) return;
        setRequirements(items);
        setLoadError(null);
      } catch (err) {
        if (cancelled) return;
        setRequirements([]);
        setLoadError(
          err instanceof Error ? err.message : "Could not load requirements.",
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

  async function act(requirementId: string, action: "approved" | "rejected") {
    setActingOn(requirementId);
    setActionError(null);
    try {
      await api.submitReviewAction(
        sessionId,
        "requirement",
        requirementId,
        action,
      );
      setReloadToken((n) => n + 1);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Could not save the review action.",
      );
    } finally {
      setActingOn(null);
    }
  }

  if (loading) return <LoadingRow label="Loading requirements…" />;
  if (loadError) return <ErrorRow message={loadError} onRetry={handleRetry} />;
  if (requirements.length === 0) {
    return (
      <EmptyRow label="No requirements captured yet - run the requirements phase to generate some." />
    );
  }

  const byCategory = requirements.reduce<Record<string, RequirementItem[]>>(
    (acc, r) => {
      (acc[r.category] ??= []).push(r);
      return acc;
    },
    {},
  );
  const categories = Object.keys(byCategory).sort((a, b) => a.localeCompare(b));

  return (
    <div className="space-y-6">
      {actionError && (
        <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          {actionError}
        </p>
      )}
      {categories.map((category) => (
        <section key={category} aria-labelledby={`req-cat-${category}`}>
          <h4
            id={`req-cat-${category}`}
            className="mb-2 text-sm font-medium text-ink-muted"
          >
            {category}
          </h4>
          <ul className="space-y-2">
            {byCategory[category].map((r) => {
              const pending = actingOn === r.id;
              return (
                <li
                  key={r.id}
                  className={`rounded-md border border-border bg-surface p-3 ${
                    pending ? "opacity-70" : ""
                  }`}
                  aria-busy={pending}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink">{r.description}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
                        {r.priority && <span>Priority: {r.priority}</span>}
                        {r.type && <span>Type: {r.type}</span>}
                      </div>
                      {r.acceptance_criteria && (
                        <p className="mt-1.5 text-xs text-ink-muted">
                          Acceptance: {r.acceptance_criteria}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <StatusBadge status={r.status} />
                      {r.status === "draft" && (
                        <div className="flex gap-1">
                          <button
                            type="button"
                            onClick={() => act(r.id, "approved")}
                            disabled={pending}
                            aria-label="Approve requirement"
                            className="rounded-md p-2 text-ink-faint hover:bg-accent-soft hover:text-accent-strong disabled:opacity-50"
                          >
                            <Check size={16} aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            onClick={() => act(r.id, "rejected")}
                            disabled={pending}
                            aria-label="Reject requirement"
                            className="rounded-md p-2 text-ink-faint hover:bg-danger-soft hover:text-danger disabled:opacity-50"
                          >
                            <X size={16} aria-hidden="true" />
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}