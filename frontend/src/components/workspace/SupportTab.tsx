import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { ErpUserRequestItem } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow } from "./shared";


/**
 * Consultant-facing view of ERP User support requests for a project.
 *
 * Distinct from the ERP User's own Support tab under /erp/p/*, which
 * shows only the caller's requests. This surface shows every request on
 * the project and lets the consultant resolve them. Resolving calls the
 * backend, which closes the pending attention item for every recipient
 * consultant in one operation.
 */
export function SupportTab({ sessionId }: { sessionId: string }) {
  const [requests, setRequests] = useState<ErpUserRequestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);


  const [searchParams] = useSearchParams();
  const focusRaw = searchParams.get("focus");
  const focusId = focusRaw?.startsWith("erp-user-request:")
    ? focusRaw.slice("erp-user-request:".length)
    : null;
  const rowRefs = useRef<Record<string, HTMLLIElement | null>>({});


  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listErpUserRequestsForProject(sessionId);
      setRequests(res.requests);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load requests.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);


  // Initial load. The async IIFE defers every setState past the first
  // await, so the effect's synchronous phase never triggers a cascading
  // render. `reload` above stays for user-triggered refreshes.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled) return;
      setLoading(true);
      setError(null);
      try {
        const res = await api.listErpUserRequestsForProject(sessionId);
        if (!cancelled) setRequests(res.requests);
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


  const handleRetry = useCallback(() => {
    reload();
  }, [reload]);


  async function resolve(requestId: string) {
    setResolvingId(requestId);
    setError(null);
    try {
      await api.resolveErpUserRequest(sessionId, requestId);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not resolve request.");
    } finally {
      setResolvingId(null);
    }
  }


  if (loading) return <LoadingRow label="Loading support requests…" />;
  if (error) return <ErrorRow message={error} onRetry={handleRetry} />;
  if (requests.length === 0) {
    return <EmptyRow label="No support requests on this project." />;
  }


  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-ink-muted">Support requests</h4>


      <ul className="space-y-2">
        {requests.map((r) => {
          const pending = resolvingId === r.id;
          const isFocused = r.id === focusId;
          return (
            <li
              key={r.id}
              ref={(el) => {
                rowRefs.current[r.id] = el;
              }}
              className={`rounded-md border bg-surface p-3 ${
                isFocused ? "border-accent ring-1 ring-accent" : "border-border"
              } ${pending ? "opacity-70" : ""}`}
              aria-busy={pending}
            >
              <div className="flex items-start justify-between gap-3">
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
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <span
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      r.status === "resolved"
                        ? "border-accent text-accent-strong"
                        : "border-border-strong text-ink-muted"
                    }`}
                  >
                    {r.status}
                  </span>
                  {r.status === "open" && (
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() => resolve(r.id)}
                      className="rounded-md border border-accent px-2 py-1 text-xs text-accent-strong disabled:opacity-50"
                    >
                      {pending ? "Resolving…" : "Resolve"}
                    </button>
                  )}
                </div>
              </div>
              {r.resolved_at && (
                <p className="mt-2 text-xs text-ink-faint">
                  Resolved{" "}
                  {new Date(r.resolved_at).toLocaleString()}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}