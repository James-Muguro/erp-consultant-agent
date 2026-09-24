import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { TestCase, TrainingStep } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow, WorkspaceCard } from "./shared";

/**
 * Test cases and training steps. The two datasets load independently:
 * a failure to fetch training steps must not hide the test cases card,
 * and vice versa. Each card owns its own loading / error / empty state.
 */
export function TestingTrainingList({ sessionId }: { sessionId: string }) {
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [trainingSteps, setTrainingSteps] = useState<TrainingStep[]>([]);
  const [loadingTests, setLoadingTests] = useState(true);
  const [loadingTraining, setLoadingTraining] = useState(true);
  const [testsError, setTestsError] = useState<string | null>(null);
  const [trainingError, setTrainingError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [testsResult, trainingResult] = await Promise.allSettled([
        api.getTestCases(sessionId),
        api.getTrainingSteps(sessionId),
      ]);
      if (cancelled) return;

      if (testsResult.status === "fulfilled") {
        setTestCases(testsResult.value.test_cases);
        setTestsError(null);
      } else {
        setTestCases([]);
        setTestsError(
          testsResult.reason instanceof Error
            ? testsResult.reason.message
            : "Could not load test cases.",
        );
      }
      if (trainingResult.status === "fulfilled") {
        setTrainingSteps(trainingResult.value.training_steps);
        setTrainingError(null);
      } else {
        setTrainingSteps([]);
        setTrainingError(
          trainingResult.reason instanceof Error
            ? trainingResult.reason.message
            : "Could not load training steps.",
        );
      }
      setLoadingTests(false);
      setLoadingTraining(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, reloadToken]);

  const handleRetry = useCallback(() => {
    setLoadingTests(true);
    setLoadingTraining(true);
    setTestsError(null);
    setTrainingError(null);
    setReloadToken((n) => n + 1);
  }, []);

  const byType = testCases.reduce<Record<string, TestCase[]>>((acc, t) => {
    (acc[t.test_type] ??= []).push(t);
    return acc;
  }, {});
  const testTypes = Object.keys(byType).sort((a, b) => a.localeCompare(b));

  return (
    <div className="space-y-6">
      <WorkspaceCard title="Test cases">
        {loadingTests ? (
          <LoadingRow label="Loading test cases…" />
        ) : testsError ? (
          <ErrorRow message={testsError} onRetry={handleRetry} />
        ) : testCases.length === 0 ? (
          <EmptyRow label="No test cases yet - run the QA or UAT testing phase to generate some." />
        ) : (
          <div className="space-y-4">
            {testTypes.map((type) => (
              <div key={type}>
                <h4 className="mb-2 text-sm font-medium text-ink-muted">{type}</h4>
                <ul className="space-y-2">
                  {byType[type].map((t) => (
                    <li key={t.id} className="rounded-md border border-border bg-paper p-3">
                      <div className="flex items-center justify-between gap-2">
                        {t.external_code && (
                          <span className="font-mono text-xs text-ink-faint">
                            {t.external_code}
                          </span>
                        )}
                        {t.priority && (
                          <span className="text-xs text-ink-faint">{t.priority}</span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-ink">{t.scenario}</p>
                      {t.expected_result && (
                        <p className="mt-1 text-xs text-ink-muted">
                          Expected: {t.expected_result}
                        </p>
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
        {loadingTraining ? (
          <LoadingRow label="Loading training steps…" />
        ) : trainingError ? (
          <ErrorRow message={trainingError} onRetry={handleRetry} />
        ) : trainingSteps.length === 0 ? (
          <EmptyRow label="No training steps yet - run the training phase to generate some." />
        ) : (
          <ul className="space-y-2">
            {trainingSteps.map((t) => (
              <li key={t.id} className="rounded-md border border-border bg-paper p-3">
                <p className="text-sm text-ink">{t.title}</p>
                {t.instructions && (
                  <p className="mt-1 text-xs text-ink-muted">{t.instructions}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </WorkspaceCard>
    </div>
  );
}