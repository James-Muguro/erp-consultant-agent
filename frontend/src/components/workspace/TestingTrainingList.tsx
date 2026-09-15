import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { TestCase, TrainingStep } from "../../types";
import { EmptyRow, WorkspaceCard } from "./shared";

export function TestingTrainingList({ sessionId }: { sessionId: string }) {
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [trainingSteps, setTrainingSteps] = useState<TrainingStep[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.getTestCases(sessionId), api.getTrainingSteps(sessionId)])
      .then(([tc, ts]) => {
        setTestCases(tc.test_cases);
        setTrainingSteps(ts.training_steps);
      })
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) return <p className="text-sm text-ink-faint">Loading testing and training records…</p>;

  const byType = testCases.reduce<Record<string, TestCase[]>>((acc, t) => {
    (acc[t.test_type] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <WorkspaceCard title="Test cases">
        {testCases.length === 0 ? (
          <EmptyRow label="No test cases yet - run the QA or UAT testing phase to generate some." />
        ) : (
          <div className="space-y-4">
            {Object.entries(byType).map(([type, items]) => (
              <div key={type}>
                <h4 className="mb-2 text-sm font-medium text-ink-muted">{type}</h4>
                <ul className="space-y-2">
                  {items.map((t) => (
                    <li key={t.id} className="rounded-md border border-border bg-paper p-3">
                      <div className="flex items-center justify-between gap-2">
                        {t.external_code && (
                          <span className="font-mono text-xs text-ink-faint">{t.external_code}</span>
                        )}
                        {t.priority && <span className="text-xs text-ink-faint">{t.priority}</span>}
                      </div>
                      <p className="mt-1 text-sm text-ink">{t.scenario}</p>
                      {t.expected_result && (
                        <p className="mt-1 text-xs text-ink-muted">Expected: {t.expected_result}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </WorkspaceCard>

      <WorkspaceCard title="Training steps">
        {trainingSteps.length === 0 ? (
          <EmptyRow label="No training steps yet - run the training phase to generate some." />
        ) : (
          <ul className="space-y-2">
            {trainingSteps.map((t) => (
              <li key={t.id} className="rounded-md border border-border bg-paper p-3">
                <p className="text-sm text-ink">{t.title}</p>
                {t.instructions && <p className="mt-1 text-xs text-ink-muted">{t.instructions}</p>}
              </li>
            ))}
          </ul>
        )}
      </WorkspaceCard>
    </div>
  );
}
