import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { TrainingMaterialsResponse } from "../../types";

function asDisplayString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return null;
}

/**
 * The training document response includes a `download_path` of the
 * shape /api/projects/{sessionId}/erp-user/training-materials/documents/{id}/download.
 * We only need the {id} segment. If the backend later adds an explicit
 * `id` field, prefer that and delete this helper.
 */
function extractTrainingDocumentId(downloadPath: string): string | null {
  const segments = downloadPath.split("/").filter(Boolean);
  const idx = segments.indexOf("documents");
  if (idx === -1 || idx + 1 >= segments.length) return null;
  return segments[idx + 1];
}

export function TrainingView() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [data, setData] = useState<TrainingMaterialsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  // Initial load. Deferred past the effect's sync phase.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled || !sessionId) return;
      try {
        const result = await api.getErpUserTrainingMaterials(sessionId);
        if (!cancelled) setData(result);
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof Error
              ? e.message
              : "Could not load training materials.",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  async function download(documentId: string, filename: string) {
    if (!sessionId) return;
    setDownloadingId(documentId);
    setError(null);
    try {
      await api.downloadErpUserTrainingDocument(
        sessionId,
        documentId,
        filename,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setDownloadingId(null);
    }
  }

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
          <p className="text-sm text-ink-muted">Loading training materials…</p>
        )}
      </section>
    );
  }

  const hasSteps = data.steps.length > 0;
  const hasDocuments = data.documents.length > 0;

  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <div className="rounded-md border border-border bg-surface p-4">
        <h2 className="text-sm font-medium text-ink">Training materials</h2>
        <p className="mt-1 text-xs text-ink-muted">
          Read-only. These materials have been prepared for you by the
          project team. Contact the functional consultant if a document or
          step appears to be missing.
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

      {!hasSteps && !hasDocuments && (
        <p className="text-sm text-ink-muted">
          No training materials have been assigned to you yet.
        </p>
      )}

      {hasDocuments && (
        <div className="rounded-md border border-border bg-surface p-4">
          <h3 className="text-sm font-medium text-ink">Documents</h3>
          <ul className="mt-2 space-y-1">
            {data.documents.map((doc, idx) => {
              const documentId = extractTrainingDocumentId(doc.download_path);
              const isDownloading = downloadingId === documentId;
              return (
                <li key={`${doc.label}-${idx}`} className="text-sm">
                  {documentId ? (
                    <button
                      type="button"
                      onClick={() => download(documentId, doc.filename)}
                      disabled={isDownloading}
                      className="text-accent-strong underline disabled:opacity-50"
                    >
                      {isDownloading ? "Preparing download…" : doc.filename}
                    </button>
                  ) : (
                    <span className="text-ink-muted">{doc.filename}</span>
                  )}
                  <span className="ml-2 text-xs text-ink-faint">
                    {doc.label}
                    {doc.generated_at
                      ? ` · ${new Date(doc.generated_at).toLocaleDateString()}`
                      : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {hasSteps && (
        <div className="rounded-md border border-border bg-surface p-4">
          <h3 className="text-sm font-medium text-ink">Steps</h3>
          <ul className="mt-2 space-y-3">
            {data.steps.map((step, idx) => {
              const externalCode = asDisplayString(step.external_code);
              const title =
                asDisplayString(step.title) ??
                asDisplayString(step.name) ??
                `Step ${idx + 1}`;
              const instructions =
                asDisplayString(step.instructions) ??
                asDisplayString(step.description);
              return (
                <li key={externalCode ?? `step-${idx}`}>
                  <p className="text-sm text-ink">
                    {externalCode && (
                      <span className="mr-2 text-xs text-ink-faint">
                        {externalCode}
                      </span>
                    )}
                    {title}
                  </p>
                  {instructions && (
                    <p className="mt-1 whitespace-pre-wrap text-xs text-ink-muted">
                      {instructions}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}