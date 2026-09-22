import { useCallback, useEffect, useRef, useState } from "react";
import { Download, FileText, Sparkles } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { DocumentRef } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow } from "./shared";

export function DeliverablesPanel({ sessionId }: { sessionId: string }) {
  const [documents, setDocuments] = useState<DocumentRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [downloadingFilename, setDownloadingFilename] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const generationRef = useRef(0);

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current;
    setLoading(true);
    setLoadError(null);
    try {
      const { documents } = await api.listDocuments(sessionId);
      if (generation !== generationRef.current) return;
      setDocuments(documents);
    } catch (err) {
      if (generation !== generationRef.current) return;
      setDocuments([]);
      setLoadError(
        err instanceof Error ? err.message : "Could not load deliverables.",
      );
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    return () => {
      generationRef.current++;
    };
  }, [refresh]);

  async function handleGenerateReport() {
    setGenerateError(null);
    setGenerating(true);
    try {
      await api.generateProjectReport(sessionId);
      await refresh();
    } catch (err) {
      // The endpoint is rate-limited at 10/min, so a 429 is plausible
      // and its message ("Rate limit exceeded: ...") is worth showing.
      setGenerateError(
        err instanceof ApiError
          ? err.message
          : "Could not generate the report.",
      );
    } finally {
      setGenerating(false);
    }
  }

  async function handleDownload(doc: DocumentRef) {
    setDownloadError(null);
    setDownloadingFilename(doc.filename);
    try {
      await api.downloadDocument(sessionId, doc.filename);
    } catch (err) {
      setDownloadError(
        err instanceof Error ? err.message : "Could not download the document.",
      );
    } finally {
      setDownloadingFilename(null);
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-ink-muted">
          Documents generated across the project - individual phase outputs, and
          a consolidated status report you can hand to a client.
        </p>
        <button
          type="button"
          onClick={handleGenerateReport}
          disabled={generating}
          className="flex shrink-0 items-center justify-center gap-2 rounded-md bg-accent px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60 sm:py-2"
        >
          <Sparkles size={14} aria-hidden="true" />
          {generating ? "Generating…" : "Generate project report"}
        </button>
      </div>

      {generateError && (
        <p
          role="alert"
          className="mb-3 rounded-md bg-danger-soft px-3 py-1.5 text-xs text-danger"
        >
          {generateError}
        </p>
      )}

      {downloadError && (
        <p
          role="alert"
          className="mb-3 rounded-md bg-danger-soft px-3 py-1.5 text-xs text-danger"
        >
          {downloadError}
        </p>
      )}

      {loading ? (
        <LoadingRow label="Loading deliverables…" />
      ) : loadError ? (
        <ErrorRow message={loadError} onRetry={refresh} />
      ) : documents.length === 0 ? (
        <EmptyRow label="No documents generated yet - run a phase, or generate a project report above." />
      ) : (
        <ul className="space-y-2">
          {documents.map((doc) => {
            const pending = downloadingFilename === doc.filename;
            return (
              <li
                key={doc.filename}
                aria-busy={pending}
                className={`flex items-center justify-between gap-3 rounded-md border border-border bg-surface p-3 ${
                  pending ? "opacity-70" : ""
                }`}
              >
                <div className="flex min-w-0 items-start gap-2">
                  <FileText
                    size={16}
                    className="mt-0.5 shrink-0 text-ink-faint"
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink">{doc.label}</p>
                    <p className="text-xs text-ink-faint">
                      {doc.phase.replace(/_/g, " ")}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleDownload(doc)}
                  disabled={pending}
                  aria-label={`Download ${doc.label}`}
                  className="shrink-0 rounded-md p-2.5 text-ink-faint hover:bg-paper hover:text-ink disabled:opacity-50"
                >
                  <Download size={15} aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}