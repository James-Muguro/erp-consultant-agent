import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { ErpUserQuestionnaireState } from "../../types";

const FALLBACK_TEMPLATE_FILENAME = "requirements-questionnaire-template.docx";

export function QuestionnaireView() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [state, setState] = useState<ErpUserQuestionnaireState | null>(null);
  const [answers, setAnswers] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seededForSessionRef = useRef<string | null>(null);

  const reload = useCallback(async () => {
    if (!sessionId) return;
    try {
      const s = await api.getErpUserQuestionnaire(sessionId);
      setState(s);
      if (s.last_submission && seededForSessionRef.current !== sessionId) {
        setAnswers(s.last_submission.answers);
        seededForSessionRef.current = sessionId;
      }
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not load questionnaire.",
      );
    }
  }, [sessionId]);

  // Initial load only; deferred past the effect's sync phase.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled || !sessionId) return;
      try {
        const s = await api.getErpUserQuestionnaire(sessionId);
        if (cancelled) return;
        setState(s);
        if (s.last_submission && seededForSessionRef.current !== sessionId) {
          setAnswers(s.last_submission.answers);
          seededForSessionRef.current = sessionId;
        }
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load questionnaire.",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  async function submit() {
    if (!sessionId || !answers.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.submitErpUserQuestionnaire(sessionId, answers);
      setFeedback(res.note);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submission failed.");
    } finally {
      setSubmitting(false);
    }
  }

  async function downloadTemplate() {
    if (!sessionId) return;
    setDownloading(true);
    setError(null);
    try {
      await api.downloadErpUserQuestionnaireTemplate(
        sessionId,
        FALLBACK_TEMPLATE_FILENAME,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <div className="rounded-md border border-border bg-surface p-4">
        <h2 className="text-sm font-medium text-ink">
          Requirements questionnaire
        </h2>
        <p className="mt-1 text-xs text-ink-muted">
          Provide your raw stakeholder input below. Your answers are
          recorded as evidence and reviewed by the functional consultant;
          they are not yet part of the structured requirements register.
        </p>
        {state?.template_available && (
          <p className="mt-2 text-xs">
            <button
              type="button"
              onClick={downloadTemplate}
              disabled={downloading}
              className="text-accent-strong underline disabled:opacity-50"
            >
              {downloading
                ? "Preparing download…"
                : "Download the questionnaire template"}
            </button>
          </p>
        )}
      </div>

      {feedback && (
        <p className="rounded-md bg-accent-soft px-3 py-2 text-sm text-accent-strong">
          {feedback}
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      <textarea
        value={answers}
        onChange={(e) => setAnswers(e.target.value)}
        rows={16}
        className="w-full rounded-md border border-border bg-surface p-3 text-sm text-ink"
        placeholder="Paste or type your answers here…"
      />
      <button
        type="button"
        onClick={submit}
        disabled={submitting || !answers.trim()}
        className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Submit answers"}
      </button>

      {state?.last_submission && (
        <p className="text-xs text-ink-faint">
          Last submitted{" "}
          {new Date(state.last_submission.submitted_at).toLocaleString()}.
        </p>
      )}
    </section>
  );
}