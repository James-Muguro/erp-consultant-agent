import { useEffect, useState } from "react";
import { Download, FileText, Sparkles } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { DocumentRef } from "../../types";
import { EmptyRow } from "./shared";

export function DeliverablesPanel({ sessionId }: { sessionId: string }) {
  const [documents, setDocuments] = useState<DocumentRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const { documents } = await api.listDocuments(sessionId);
      setDocuments(documents);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function handleGenerateReport() {
    setError(null);
    setGenerating(true);
    try {
      await api.generateProjectReport(sessionId);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate the report.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-ink-muted">
          Documents generated across the project - individual phase outputs, and a consolidated
          status report you can hand to a client.
        </p>
        <button
          onClick={handleGenerateReport}
          disabled={generating}
          className="flex shrink-0 items-center justify-center gap-2 rounded-md bg-accent px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60 sm:py-2"
        >
          <Sparkles size={14} />
          {generating ? "Generating…" : "Generate project report"}
        </button>
      </div>

      {error && <p role="alert" className="mb-3 rounded-md bg-danger-soft px-3 py-1.5 text-xs text-danger">{error}</p>}

      {loading ? (
        <p className="text-sm text-ink-faint">Loading deliverables…</p>
      ) : documents.length === 0 ? (
        <EmptyRow label="No documents generated yet - run a phase, or generate a project report above." />
      ) : (
        <ul className="space-y-2">
          {documents.map((doc) => (
            <li
              key={doc.filename}
              className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface p-3"
            >
              <div className="flex min-w-0 items-start gap-2">
                <FileText size={16} className="mt-0.5 shrink-0 text-ink-faint" />
                <div className="min-w-0">
                  <p className="truncate text-sm text-ink">{doc.label}</p>
                  <p className="text-xs text-ink-faint">{doc.phase.replace(/_/g, " ")}</p>
                </div>
              </div>
              <button
                onClick={() => api.downloadDocument(sessionId, doc.filename)}
                aria-label={`Download ${doc.label}`}
                className="shrink-0 rounded-md p-2.5 text-ink-faint hover:bg-paper hover:text-ink"
              >
                <Download size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
