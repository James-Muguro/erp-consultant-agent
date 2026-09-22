import { useCallback, useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";
import { api } from "../../api/client";
import type { RequirementItem } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow, StatusBadge } from "./shared";

/**
 * Requirements tab. Loads requirements, groups them by category, and
 * offers approve/reject on drafts.
 *
 * Every failure path here is now honest: a failed load shows an error
 * with retry, not an empty list; a failed review action surfaces the
 * backend's message instead of silently reverting. The request-generation
 * counter invalidates in-flight responses when the session changes or a
 * manual refresh supersedes an earlier one, so a slow response for an
 * old request cannot overwrite current state.
 */
export function RequirementsList({ sessionId }: { sessionId: string }) {
  const [requirements, setRequirements] = useState<RequirementItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Increments on every refresh (including the cleanup on unmount /
  // session change). A response whose generation does not match the
  // current counter is discarded.
  const generationRef = useRef(0);

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current;
    setLoading(true);
    setLoadError(null);
    try {
      const { requirements } = await api.getRequirements(sessionId);
      if (generation !== generationRef.current) return;
      setRequirements(requirements);
    } catch (err) {
      if (generation !== generationRef.current) return;
      setRequirements([]);
      setLoadError(
        err instanceof Error ? err.message : "Could not load requirements.",
      );
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    return () => {
      // Invalidate any in-flight response when sessionId changes or the
      // component unmounts.
      generationRef.current++;
    };
  }, [refresh]);

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
      await refresh();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Could not save the review action.",
      );
    } finally {
      setActingOn(null);
    }
  }

  if (loading) return <LoadingRow label="Loading requirements…" />;
  if (loadError) return <ErrorRow message={loadError} onRetry={refresh} />;
  if (requirements.length === 0) {
    return (
      <EmptyRow label="No requirements captured yet - run the requirements phase to generate some." />
    );
  }

  // Group by category. Insertion order of `byCategory` mirrors first
  // appearance in the (backend-ordered) list. We sort the category names
  // to keep the tab stable across refreshes - previously the order could
  // reshuffle if the backend returned the same categories in a different
  // first-seen order.
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