import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { useCapabilities } from "../../auth/useCapabilities";
import type { TestCase, TrainingStep } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow, WorkspaceCard } from "./shared";

const ACTIVE_STATUSES =
  "open,developer_marked_complete,reopened_with_feedback";

const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  developer_marked_complete: "Awaiting confirmation",
  reopened_with_feedback: "Reopened with feedback",
  consultant_confirmed_resolved: "Resolved",
};

export function TestingTrainingList({ sessionId }: { sessionId: string }) {
  const capabilities = useCapabilities();
  const canComplete = capabilities.can("testing:write");
  const canReview = capabilities.can("reviews:submit");

  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [trainingSteps, setTrainingSteps] = useState<TrainingStep[]>([]);
  const [loadingTests, setLoadingTests] = useState(true);
  const [loadingTraining, setLoadingTraining] = useState(true);
  const [testsError, setTestsError] = useState<string | null>(null);
  const [trainingError, setTrainingError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [reopeningFor, setReopeningFor] = useState<string | null>(null);
  const [reopenNote, setReopenNote] = useState("");

  const [searchParams] = useSearchParams();
  const focusRaw = searchParams.get("focus");
  const focusId = focusRaw?.startsWith("test_case:")
    ? focusRaw.slice("test_case:".length)
    : null;
  const rowRefs = useRef<Record<string, HTMLLIElement | null>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [testsResult, trainingResult] = await Promise.allSettled([
        api.getTestCases(sessionId, ACTIVE_STATUSES),
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

  useEffect(() => {
    if (!focusId || loadingTests) return;
    const el = rowRefs.current[focusId];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [focusId, loadingTests, testCases]);

  async function act(
    testCaseId: string,
    kind: "complete" | "confirm" | "reopen",
    note?: string,
  ) {
    setActingOn(testCaseId);
    setActionError(null);
    try {
      if (kind === "complete") {
        await api.markTestCaseDeveloperComplete(sessionId, testCaseId);
      } else if (kind === "confirm") {
        await api.confirmTestCaseResolved(sessionId, testCaseId);
      } else {
        await api.reopenTestCase(sessionId, testCaseId, note ?? "");
      }
      setReopeningFor(null);
      setReopenNote("");
      setReloadToken((n) => n + 1);
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Could not save the action.",
      );
    } finally {
      setActingOn(null);
    }
  }

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
          <EmptyRow label="No active test cases - run the QA or UAT testing phase to generate some." />
        ) : (
          <div className="space-y-4">
            {actionError && (
              <p
                role="alert"
                className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
              >
                {actionError}
              </p>
            )}
            {testTypes.map((type) => (
              <div key={type}>
                <h4 className="mb-2 text-sm font-medium text-ink-muted">
                  {type}
                </h4>
                <ul className="space-y-2">
                  {byType[type].map((t) => {
                    const pending = actingOn === t.id;
                    const showComplete =
                      canComplete &&
                      (t.status === "open" ||
                        t.status === "reopened_with_feedback");
                    const showReview =
                      canReview && t.status === "developer_marked_complete";
                    return (
                      <li
                        key={t.id}
                        ref={(el) => {
                          rowRefs.current[t.id] = el;
                        }}
                        className={`rounded-md border bg-paper p-3 ${
                          t.id === focusId
                            ? "border-accent ring-1 ring-accent"
                            : "border-border"
                        } ${pending ? "opacity-70" : ""}`}
                        aria-busy={pending}
                      >
                        <div className="flex items-center justify-between gap-2">
                          {t.external_code && (
                            <span className="font-mono text-xs text-ink-faint">
                              {t.external_code}
                            </span>
                          )}
                          <span className="text-xs text-ink-faint">
                            {STATUS_LABEL[t.status] ?? t.status}
                          </span>
                          {t.priority && (
                            <span className="text-xs text-ink-faint">
                              {t.priority}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-sm text-ink">{t.scenario}</p>
                        {t.expected_result && (
                          <p className="mt-1 text-xs text-ink-muted">
                            Expected: {t.expected_result}
                          </p>
                        )}
                        {t.status === "reopened_with_feedback" &&
                          t.reopen_note && (
                            <p className="mt-2 rounded-md bg-warning-soft px-2 py-1 text-xs text-ink">
                              Reopened: {t.reopen_note}
                              {t.reopen_at && (
                                <span className="ml-1 text-ink-faint">
                                  ({new Date(t.reopen_at).toLocaleString()})
                                </span>
                              )}
                            </p>
                          )}
                        {(showComplete || showReview) && (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {showComplete && (
                              <button
                                type="button"
                                disabled={pending}
                                onClick={() => act(t.id, "complete")}
                                className="rounded-md border border-accent px-2 py-1 text-xs text-accent-strong disabled:opacity-50"
                              >
                                {pending ? "Saving…" : "Mark complete"}
                              </button>
                            )}
                            {showReview && (
                              <>
                                <button
                                  type="button"
                                  disabled={pending}
                                  onClick={() => act(t.id, "confirm")}
                                  className="rounded-md border border-accent px-2 py-1 text-xs text-accent-strong disabled:opacity-50"
                                >
                                  Confirm resolved
                                </button>
                                <button
                                  type="button"
                                  disabled={pending}
                                  onClick={() => {
                                    setReopeningFor(t.id);
                                    setReopenNote("");
                                  }}
                                  className="rounded-md border border-border px-2 py-1 text-xs text-ink-muted hover:border-danger hover:text-danger disabled:opacity-50"
                                >
                                  Reopen
                                </button>
                              </>
                            )}
                          </div>
                        )}
                        {reopeningFor === t.id && (
                          <div className="mt-3 space-y-2 rounded-md border border-border bg-surface p-2">
                            <textarea
                              value={reopenNote}
                              onChange={(e) => setReopenNote(e.target.value)}
                              rows={2}
                              placeholder="Explain what still needs to be done…"
                              className="w-full rounded-md border border-border bg-surface p-2 text-xs"
                            />
                            <div className="flex gap-2">
                              <button
                                type="button"
                                disabled={pending || !reopenNote.trim()}
                                onClick={() =>
                                  act(t.id, "reopen", reopenNote.trim())
                                }
                                className="rounded-md bg-danger-soft px-2 py-1 text-xs text-danger disabled:opacity-50"
                              >
                                Send back to developer
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setReopeningFor(null);
                                  setReopenNote("");
                                }}
                                className="rounded-md border border-border px-2 py-1 text-xs text-ink-muted"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}
                      </li>
                    );
                  })}
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
              <li
                key={t.id}
                className="rounded-md border border-border bg-paper p-3"
              >
                <p className="text-sm text-ink">{t.title}</p>
                {t.instructions && (
                  <p className="mt-1 text-xs text-ink-muted">
                    {t.instructions}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </WorkspaceCard>
    </div>
  );
}