import { useCallback, useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";
import { api } from "../../api/client";
import type { SolutionDecision } from "../../types";
import {
  EmptyRow,
  ErrorRow,
  LinkedRequirementBadge,
  LoadingRow,
  StatusBadge,
} from "./shared";

export function SolutionDecisionsList({ sessionId }: { sessionId: string }) {
  const [decisions, setDecisions] = useState<SolutionDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const generationRef = useRef(0);

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current;
    setLoading(true);
    setLoadError(null);
    try {
      const { solution_decisions } = await api.getSolutionDecisions(sessionId);
      if (generation !== generationRef.current) return;
      setDecisions(solution_decisions);
    } catch (err) {
      if (generation !== generationRef.current) return;
      setDecisions([]);
      setLoadError(
        err instanceof Error
          ? err.message
          : "Could not load solution decisions.",
      );
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    return () => {
      generationRef.current++;
    };
  }, [refresh]);

  async function act(
    decisionId: string,
    action: "approved" | "rejected",
  ) {
    setActingOn(decisionId);
    setActionError(null);
    try {
      await api.submitReviewAction(
        sessionId,
        "solution_decision",
        decisionId,
        action,
      );
      await refresh();
    } catch (err) {
      setActionError(
        err instanceof Error
          ? err.message
          : "Could not save the review action.",
      );
    } finally {
      setActingOn(null);
    }
  }

  if (loading) return <LoadingRow label="Loading solution decisions…" />;
  if (loadError) return <ErrorRow message={loadError} onRetry={refresh} />;
  if (decisions.length === 0) {
    return (
      <EmptyRow label="No solution decisions recorded yet - run the solution design phase to generate some." />
    );
  }

  const byType = decisions.reduce<Record<string, SolutionDecision[]>>(
    (acc, d) => {
      (acc[d.decision_type] ??= []).push(d);
      return acc;
    },
    {},
  );
  const types = Object.keys(byType).sort((a, b) => a.localeCompare(b));

  return (
    <div className="space-y-6">
      {actionError && (
        <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          {actionError}
        </p>
      )}
      {types.map((type) => (
        <section key={type} aria-labelledby={`dec-${type}`}>
          <h4
            id={`dec-${type}`}
            className="mb-2 text-sm font-medium text-ink-muted"
          >
            {type.replace(/_/g, " ")}
          </h4>
          <ul className="space-y-2">
            {byType[type].map((d) => {
              const pending = actingOn === d.id;
              return (
                <li
                  key={d.id}
                  aria-busy={pending}
                  className={`rounded-md border border-border bg-surface p-3 ${
                    pending ? "opacity-70" : ""
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      {d.component && (
                        <p className="text-xs font-medium text-ink-muted">
                          {d.component}
                        </p>
                      )}
                      <p className="text-sm text-ink">{d.description}</p>
                      {d.rationale && (
                        <p className="mt-1 text-xs text-ink-muted">
                          Rationale: {d.rationale}
                        </p>
                      )}
                      <div className="mt-1.5">
                        <LinkedRequirementBadge requirementId={d.requirement_id} />
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <StatusBadge status={d.status} />
                      {d.status === "draft" && (
                        <div className="flex gap-1">
                          <button
                            type="button"
                            onClick={() => act(d.id, "approved")}
                            disabled={pending}
                            aria-label="Approve solution decision"
                            className="rounded-md p-2 text-ink-faint hover:bg-accent-soft hover:text-accent-strong disabled:opacity-50"
                          >
                            <Check size={16} aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            onClick={() => act(d.id, "rejected")}
                            disabled={pending}
                            aria-label="Reject solution decision"
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