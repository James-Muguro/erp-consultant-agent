import { useEffect, useRef, useState } from "react";
import { Download, FileText, Trash2, Upload } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { UploadedDocument } from "../../types";
import { EmptyRow } from "./shared";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadsPanel({ sessionId }: { sessionId: string }) {
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function refresh() {
    setLoading(true);
    try {
      const { documents } = await api.listUploads(sessionId);
      setDocuments(documents);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function handleFileChosen(file: File | undefined) {
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      await api.uploadDocument(sessionId, file);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm("Delete this document? This cannot be undone.")) return;
    await api.deleteUpload(sessionId, id);
    await refresh();
  }

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-ink-muted">
          Upload project documents (PDF, DOCX, TXT, MD) for agents to reference in later phases.
        </p>
        <label className="flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-md bg-accent px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong sm:py-2">
          <Upload size={14} />
          {uploading ? "Uploading…" : "Upload"}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            className="hidden"
            disabled={uploading}
            onChange={(e) => handleFileChosen(e.target.files?.[0])}
          />
        </label>
      </div>

      {error && <p role="alert" className="mb-3 rounded-md bg-danger-soft px-3 py-1.5 text-xs text-danger">{error}</p>}

      {loading ? (
        <p className="text-sm text-ink-faint">Loading documents…</p>
      ) : documents.length === 0 ? (
        <EmptyRow label="No documents uploaded yet." />
      ) : (
        <ul className="space-y-2">
          {documents.map((doc) => (
            <li
              key={doc.id}
              className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface p-3"
            >
              <div className="flex min-w-0 items-start gap-2">
                <FileText size={16} className="mt-0.5 shrink-0 text-ink-faint" />
                <div className="min-w-0">
                  <p className="truncate text-sm text-ink">{doc.filename}</p>
                  <p className="text-xs text-ink-faint">
                    {formatSize(doc.size_bytes)}
                    {doc.extracted_text_chars === 0
                      ? " — no text could be extracted"
                      : ` — ${doc.extracted_text_chars.toLocaleString()} characters available to agents`}
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  onClick={() => api.downloadUpload(sessionId, doc.id, doc.filename)}
                  aria-label={`Download ${doc.filename}`}
                  className="rounded-md p-2.5 text-ink-faint hover:bg-paper hover:text-ink"
                >
                  <Download size={15} />
                </button>
                <button
                  onClick={() => handleDelete(doc.id)}
                  aria-label={`Delete ${doc.filename}`}
                  className="rounded-md p-2.5 text-ink-faint hover:bg-danger-soft hover:text-danger"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
