import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { ProcessStep } from "../../types";
import { EmptyRow, ErrorRow, LinkedRequirementBadge, LoadingRow } from "./shared";

export function ProcessStepsList({ sessionId }: { sessionId: string }) {
  const [steps, setSteps] = useState<ProcessStep[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { process_steps } = await api.getProcessSteps(sessionId);
        if (cancelled) return;
        setSteps(process_steps);
        setLoadError(null);
      } catch (err) {
        if (cancelled) return;
        setSteps([]);
        setLoadError(
          err instanceof Error ? err.message : "Could not load process steps.",
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

  if (loading) return <LoadingRow label="Loading process steps…" />;
  if (loadError) return <ErrorRow message={loadError} onRetry={handleRetry} />;
  if (steps.length === 0) {
    return (
      <EmptyRow label="No process steps captured yet - run the process mapping phase to generate some." />
    );
  }

  const byProcess = steps.reduce<Record<string, ProcessStep[]>>((acc, s) => {
    (acc[s.process_name] ??= []).push(s);
    return acc;
  }, {});
  const processNames = Object.keys(byProcess).sort((a, b) => a.localeCompare(b));

  return (
    <div className="space-y-6">
      {processNames.map((processName) => {
        const ordered = [...byProcess[processName]].sort(
          (a, b) => a.step_number - b.step_number,
        );
        return (
          <section key={processName} aria-labelledby={`proc-${processName}`}>
            <h4
              id={`proc-${processName}`}
              className="mb-2 text-sm font-medium text-ink-muted"
            >
              {processName}
            </h4>
            <ol className="space-y-2">
              {ordered.map((s) => (
                <li
                  key={s.id}
                  className="flex gap-3 rounded-md border border-border bg-surface p-3"
                >
                  <span className="mt-0.5 shrink-0 font-mono text-xs text-ink-faint">
                    {s.step_number}.
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink">{s.name}</p>
                    {s.description && (
                      <p className="mt-1 text-xs text-ink-muted">{s.description}</p>
                    )}
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      {s.responsible_role && (
                        <span className="text-xs text-ink-faint">
                          Owner: {s.responsible_role}
                        </span>
                      )}
                      <LinkedRequirementBadge requirementId={s.requirement_id} />
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        );
      })}
    </div>
  );
}