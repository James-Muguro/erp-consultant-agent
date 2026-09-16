import { useEffect, useState } from "react";
import { Check, X } from "lucide-react";
import { api } from "../../api/client";
import type { SolutionDecision } from "../../types";
import { EmptyRow, LinkedRequirementBadge, StatusBadge } from "./shared";

export function SolutionDecisionsList({ sessionId }: { sessionId: string }) {
  const [decisions, setDecisions] = useState<SolutionDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [actingOn, setActingOn] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const { solution_decisions } = await api.getSolutionDecisions(sessionId);
      setDecisions(solution_decisions);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function act(decisionId: string, action: "approved" | "rejected") {
    setActingOn(decisionId);
    try {
      await api.submitReviewAction(sessionId, "solution_decision", decisionId, action);
      await refresh();
    } finally {
      setActingOn(null);
    }
  }

  if (loading) return <p className="text-sm text-ink-faint">Loading solution decisions…</p>;
  if (decisions.length === 0) {
    return <EmptyRow label="No solution decisions recorded yet - run the solution design phase to generate some." />;
  }

  const byType = decisions.reduce<Record<string, SolutionDecision[]>>((acc, d) => {
    (acc[d.decision_type] ??= []).push(d);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {Object.entries(byType).map(([type, items]) => (
        <div key={type}>
          <h4 className="mb-2 text-sm font-medium text-ink-muted">{type.replace(/_/g, " ")}</h4>
          <ul className="space-y-2">
            {items.map((d) => (
              <li key={d.id} className="rounded-md border border-border bg-surface p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    {d.component && <p className="text-xs font-medium text-ink-muted">{d.component}</p>}
                    <p className="text-sm text-ink">{d.description}</p>
                    {d.rationale && <p className="mt-1 text-xs text-ink-muted">Rationale: {d.rationale}</p>}
                    <div className="mt-1.5">
                      <LinkedRequirementBadge requirementId={d.requirement_id} />
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusBadge status={d.status} />
                    {d.status === "draft" && (
                      <div className="flex gap-1">
                        <button
                          onClick={() => act(d.id, "approved")}
                          disabled={actingOn === d.id}
                          aria-label="Approve solution decision"
                          className="rounded-md p-2 text-ink-faint hover:bg-accent-soft hover:text-accent-strong disabled:opacity-50"
                        >
                          <Check size={16} />
                        </button>
                        <button
                          onClick={() => act(d.id, "rejected")}
                          disabled={actingOn === d.id}
                          aria-label="Reject solution decision"
                          className="rounded-md p-2 text-ink-faint hover:bg-danger-soft hover:text-danger disabled:opacity-50"
                        >
                          <X size={16} />
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
