import { useEffect, useState } from "react";
import { Check, X } from "lucide-react";
import { api } from "../../api/client";
import type { RequirementItem } from "../../types";
import { EmptyRow, StatusBadge } from "./shared";

export function RequirementsList({ sessionId }: { sessionId: string }) {
  const [requirements, setRequirements] = useState<RequirementItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [actingOn, setActingOn] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const { requirements } = await api.getRequirements(sessionId);
      setRequirements(requirements);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function act(requirementId: string, action: "approved" | "rejected") {
    setActingOn(requirementId);
    try {
      await api.submitReviewAction(sessionId, "requirement", requirementId, action);
      await refresh();
    } finally {
      setActingOn(null);
    }
  }

  if (loading) return <p className="text-sm text-ink-faint">Loading requirements…</p>;
  if (requirements.length === 0) {
    return <EmptyRow label="No requirements captured yet - run the requirements phase to generate some." />;
  }

  const byCategory = requirements.reduce<Record<string, RequirementItem[]>>((acc, r) => {
    (acc[r.category] ??= []).push(r);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {Object.entries(byCategory).map(([category, items]) => (
        <div key={category}>
          <h4 className="mb-2 text-sm font-medium text-ink-muted">{category}</h4>
          <ul className="space-y-2">
            {items.map((r) => (
              <li key={r.id} className="rounded-md border border-border bg-surface p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink">{r.description}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
                      {r.priority && <span>Priority: {r.priority}</span>}
                      {r.type && <span>Type: {r.type}</span>}
                    </div>
                    {r.acceptance_criteria && (
                      <p className="mt-1.5 text-xs text-ink-muted">Acceptance: {r.acceptance_criteria}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusBadge status={r.status} />
                    {r.status === "draft" && (
                      <div className="flex gap-1">
                        <button
                          onClick={() => act(r.id, "approved")}
                          disabled={actingOn === r.id}
                          title="Approve"
                          className="rounded-sm p-1 text-ink-faint hover:bg-accent-soft hover:text-accent-strong disabled:opacity-50"
                        >
                          <Check size={15} />
                        </button>
                        <button
                          onClick={() => act(r.id, "rejected")}
                          disabled={actingOn === r.id}
                          title="Reject"
                          className="rounded-sm p-1 text-ink-faint hover:bg-danger-soft hover:text-danger disabled:opacity-50"
                        >
                          <X size={15} />
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
