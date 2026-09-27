import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { FrdStatus } from "../../types";

const FALLBACK_FRD_FILENAME = "frd.docx";

export function FrdView() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [status, setStatus] = useState<FrdStatus | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!sessionId) return;
    try {
      setStatus(await api.getErpUserFrd(sessionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load FRD.");
    }
  }, [sessionId]);

  // Initial load. Deferred past the effect's sync phase; reload above
  // stays for the sign-off handler.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled || !sessionId) return;
      try {
        const result = await api.getErpUserFrd(sessionId);
        if (!cancelled) setStatus(result);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load FRD.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  async function sign(decision: "confirm" | "request_changes") {
    if (!sessionId || !status?.current_revision_id) return;
    setBusy(true);
    setError(null);
    try {
      await api.signOffErpUserFrd(
        sessionId,
        status.current_revision_id,
        decision,
        note.trim() || undefined,
      );
      setNote("");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-off failed.");
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    if (!sessionId || !status?.current_filename) return;
    setDownloading(true);
    setError(null);
    try {
      await api.downloadErpUserFrd(
        sessionId,
        status.current_filename || FALLBACK_FRD_FILENAME,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setDownloading(false);
    }
  }

  if (!status) {
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
          <p className="text-sm text-ink-muted">Loading FRD…</p>
        )}
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <div className="rounded-md border border-border bg-surface p-4">
        <h2 className="text-sm font-medium text-ink">
          Functional Requirements Document
        </h2>
        {status.current_revision_id ? (
          <>
            <p className="mt-1 text-xs text-ink-muted">
              {status.current_filename} · generated{" "}
              {status.current_generated_at
                ? new Date(status.current_generated_at).toLocaleString()
                : "—"}
            </p>
            <p className="mt-2 text-xs">
              <button
                type="button"
                onClick={download}
                disabled={downloading}
                className="text-accent-strong underline disabled:opacity-50"
              >
                {downloading ? "Preparing download…" : "Download the FRD"}
              </button>
            </p>
          </>
        ) : (
          <p className="mt-1 text-xs text-ink-muted">
            No FRD has been generated yet.
          </p>
        )}
      </div>

      {status.signoff_stale && (
        <p className="rounded-md bg-warning-soft px-3 py-2 text-sm text-ink">
          Your prior sign-off was on a previous revision. The FRD has been
          regenerated; please review and sign again if appropriate.
        </p>
      )}

      {status.signed_revision_id && !status.signoff_stale && (
        <p className="rounded-md bg-accent-soft px-3 py-2 text-sm text-accent-strong">
          Signed (
          {status.signed_action === "approved" ? "confirmed" : "changes requested"}
          ) on{" "}
          {status.signed_at ? new Date(status.signed_at).toLocaleString() : "—"}
          {status.signed_note && <> — “{status.signed_note}”</>}
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

      {status.can_sign_off && (
        <div className="rounded-md border border-border bg-surface p-4 space-y-3">
          <h3 className="text-sm font-medium text-ink">Sign-off</h3>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="Optional note (required context for 'Request changes')"
            className="w-full rounded-md border border-border bg-surface p-2 text-sm"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => sign("confirm")}
              className="rounded-md bg-accent px-3 py-2 text-sm text-white disabled:opacity-50"
            >
              Confirm
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => sign("request_changes")}
              className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger disabled:opacity-50"
            >
              Request changes
            </button>
          </div>
        </div>
      )}
    </section>
  );
}