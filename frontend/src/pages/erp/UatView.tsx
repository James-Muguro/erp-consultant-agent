import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { UatScenariosResponse } from "../../types";

export function UatView() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [data, setData] = useState<UatScenariosResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled || !sessionId) return;
      try {
        const result = await api.getErpUserUatScenarios(sessionId);
        if (!cancelled) setData(result);
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load UAT scenarios.",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (!data) {
    return (
      <section className="mx-auto max-w-3xl space-y-4">
        {error ? (
          <p
            role="alert"
            className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        ) : (
          <p className="text-sm text-ink-muted">Loading UAT scenarios…</p>
        )}
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <div className="rounded-md border border-border bg-surface p-4">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-sm font-medium text-ink">UAT scenarios</h2>
          {data.is_uat_participant && (
            <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs text-accent-strong">
              UAT participant
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-ink-muted">
          Read-only. These scenarios are prepared by the project team for
          user acceptance testing. Contact the functional consultant if
          you believe scenarios are missing or need correction.
        </p>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {data.scenarios.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No UAT scenarios have been prepared yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {data.scenarios.map((scenario, idx) => (
            <li
              key={scenario.id ?? `scenario-${idx}`}
              className="rounded-md border border-border bg-surface p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm text-ink">{scenario.scenario}</p>
                {scenario.priority && (
                  <span className="shrink-0 text-xs text-ink-faint">
                    Priority: {scenario.priority}
                  </span>
                )}
              </div>
              {scenario.expected_result && (
                <p className="mt-1.5 text-xs text-ink-muted">
                  Expected: {scenario.expected_result}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}