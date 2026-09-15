import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { ProcessStep } from "../../types";
import { EmptyRow, LinkedRequirementBadge } from "./shared";

export function ProcessStepsList({ sessionId }: { sessionId: string }) {
  const [steps, setSteps] = useState<ProcessStep[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .getProcessSteps(sessionId)
      .then(({ process_steps }) => setSteps(process_steps))
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) return <p className="text-sm text-ink-faint">Loading process steps…</p>;
  if (steps.length === 0) {
    return <EmptyRow label="No process steps captured yet - run the process mapping phase to generate some." />;
  }

  const byProcess = steps.reduce<Record<string, ProcessStep[]>>((acc, s) => {
    (acc[s.process_name] ??= []).push(s);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {Object.entries(byProcess).map(([processName, items]) => (
        <div key={processName}>
          <h4 className="mb-2 text-sm font-medium text-ink-muted">{processName}</h4>
          <ol className="space-y-2">
            {items
              .sort((a, b) => a.step_number - b.step_number)
              .map((s) => (
                <li key={s.id} className="flex gap-3 rounded-md border border-border bg-surface p-3">
                  <span className="mt-0.5 shrink-0 font-mono text-xs text-ink-faint">{s.step_number}.</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink">{s.name}</p>
                    {s.description && <p className="mt-1 text-xs text-ink-muted">{s.description}</p>}
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      {s.responsible_role && (
                        <span className="text-xs text-ink-faint">Owner: {s.responsible_role}</span>
                      )}
                      <LinkedRequirementBadge requirementId={s.requirement_id} />
                    </div>
                  </div>
                </li>
              ))}
          </ol>
        </div>
      ))}
    </div>
  );
}
