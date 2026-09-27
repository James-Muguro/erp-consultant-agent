import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { ErpUserRequestItem } from "../../types";


const REQUEST_TYPES = ["change", "question", "issue", "other"] as const;
type RequestType = (typeof REQUEST_TYPES)[number];


export function SupportView() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [searchParams] = useSearchParams();
  const focusRaw = searchParams.get("focus");
  const focusId = focusRaw?.startsWith("erp-user-request:")
    ? focusRaw.slice("erp-user-request:".length)
    : null;
  const rowRefs = useRef<Record<string, HTMLLIElement | null>>({});
  const [requests, setRequests] = useState<ErpUserRequestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [requestType, setRequestType] = useState<RequestType>("question");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);


  const reload = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await api.listErpUserRequestsForMe(sessionId);
      setRequests(res.requests);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load requests.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);


  // Initial load only; deferred past the effect's sync phase.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled || !sessionId) return;
      try {
        const res = await api.listErpUserRequestsForMe(sessionId);
        if (cancelled) return;
        setRequests(res.requests);
        setError(null);
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load requests.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);


  useEffect(() => {
    if (!focusId || loading) return;
    const el = rowRefs.current[focusId];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [focusId, loading, requests]);


  async function submit() {
    if (!sessionId || !subject.trim() || !body.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.createErpUserRequest(sessionId, {
        request_type: requestType,
        subject: subject.trim(),
        body: body.trim(),
      });
      setSubject("");
      setBody("");
      setFeedback(
        "Your request has been sent to the project's functional consultants.",
      );
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit request.");
    } finally {
      setSubmitting(false);
    }
  }


  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <div className="rounded-md border border-border bg-surface p-4">
        <h2 className="text-sm font-medium text-ink">Support</h2>
        <p className="mt-1 text-xs text-ink-muted">
          Raise a request for the project's functional consultants. This is
          separate from questionnaire answers; use it for changes,
          questions, or issues that need a consultant's attention.
        </p>
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


      <div className="rounded-md border border-border bg-surface p-4 space-y-3">
        <h3 className="text-sm font-medium text-ink">New request</h3>
        <div className="flex gap-2">
          <label className="text-xs text-ink-muted" htmlFor="erp-req-type">
            Type
          </label>
          <select
            id="erp-req-type"
            value={requestType}
            onChange={(e) => setRequestType(e.target.value as RequestType)}
            className="rounded-md border border-border bg-surface px-2 py-1 text-xs"
          >
            {REQUEST_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <input
          type="text"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Subject"
          maxLength={200}
          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
        />
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={5}
          placeholder="Describe the request…"
          maxLength={10000}
          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={submit}
          disabled={submitting || !subject.trim() || !body.trim()}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? "Submitting…" : "Submit request"}
        </button>
      </div>


      <div className="rounded-md border border-border bg-surface p-4">
        <h3 className="text-sm font-medium text-ink">My requests</h3>
        {loading ? (
          <p className="mt-2 text-xs text-ink-muted">Loading…</p>
        ) : requests.length === 0 ? (
          <p className="mt-2 text-xs text-ink-muted">No requests yet.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {requests.map((r) => (
              <li
                key={r.id}
                ref={(el) => {
                  rowRefs.current[r.id] = el;
                }}
                className={`rounded-md border bg-paper p-3 ${
                  r.id === focusId
                    ? "border-accent ring-1 ring-accent"
                    : "border-border"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink">{r.subject}</p>
                    <p className="mt-0.5 text-xs text-ink-muted">
                      {r.request_type} ·{" "}
                      {r.created_at
                        ? new Date(r.created_at).toLocaleString()
                        : ""}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-xs text-ink-muted">
                      {r.body}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${
                      r.status === "resolved"
                        ? "border-accent text-accent-strong"
                        : "border-border-strong text-ink-muted"
                    }`}
                  >
                    {r.status}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}