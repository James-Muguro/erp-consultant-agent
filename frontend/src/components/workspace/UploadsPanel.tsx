import { useCallback, useEffect, useRef, useState } from "react";
import { Download, FileText, Trash2, Upload } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { UploadedDocument } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow } from "./shared";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Uploaded project documents. Two backend states this surface cares
 * about:
 *
 *  - 503 from POST /uploads means object storage isn't configured on
 *    this server. Detected once, then surfaced as a persistent banner
 *    with a retry that clears the flag - better than letting the user
 *    pick a file only to be told it can't work after the wait.
 *  - 502 from GET /uploads/:id/download means storage is configured but
 *    the read failed (bucket gone, credentials rotated). Surfaced per
 *    download.
 */
export function UploadsPanel({ sessionId }: { sessionId: string }) {
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadsUnavailable, setUploadsUnavailable] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const generationRef = useRef(0);

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current;
    setLoading(true);
    setLoadError(null);
    try {
      const { documents } = await api.listUploads(sessionId);
      if (generation !== generationRef.current) return;
      setDocuments(documents);
    } catch (err) {
      if (generation !== generationRef.current) return;
      setDocuments([]);
      setLoadError(
        err instanceof Error ? err.message : "Could not load uploaded documents.",
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

  async function handleFileChosen(file: File | undefined) {
    if (!file) return;
    setUploadError(null);
    setUploading(true);
    try {
      await api.uploadDocument(sessionId, file);
      await refresh();
    } catch (err) {
      // 503 is the backend's explicit "object storage isn't configured"
      // signal. Detect it once and switch the panel into a state where
      // the upload button is disabled and a persistent explanation is
      // shown, rather than letting the user retry and hit the same 503.
      if (err instanceof ApiError && err.status === 503) {
        setUploadsUnavailable(true);
      }
      setUploadError(
        err instanceof Error ? err.message : "Upload failed.",
      );
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDownload(doc: UploadedDocument) {
    setRowError(null);
    setDownloadingId(doc.id);
    try {
      await api.downloadUpload(sessionId, doc.id, doc.filename);
    } catch (err) {
      setRowError(
        err instanceof Error ? err.message : "Could not download the document.",
      );
    } finally {
      setDownloadingId(null);
    }
  }

  async function handleDelete(doc: UploadedDocument) {
    if (
      !window.confirm(
        `Delete "${doc.filename}"? This cannot be undone.`,
      )
    ) {
      return;
    }
    setRowError(null);
    setDeletingId(doc.id);
    try {
      await api.deleteUpload(sessionId, doc.id);
      await refresh();
    } catch (err) {
      setRowError(
        err instanceof Error ? err.message : "Could not delete the document.",
      );
    } finally {
      setDeletingId(null);
    }
  }

  const uploadDisabled = uploading || uploadsUnavailable;

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-ink-muted">
          Upload project documents (PDF, DOCX, TXT, MD) for agents to reference in later phases.
        </p>
        <label
          className={`flex shrink-0 items-center justify-center gap-2 rounded-md px-3 py-2.5 text-sm font-medium text-white transition-colors sm:py-2 ${
            uploadDisabled
              ? "cursor-not-allowed bg-accent opacity-60"
              : "cursor-pointer bg-accent hover:bg-accent-strong"
          }`}
        >
          <Upload size={14} aria-hidden="true" />
          {uploading ? "Uploading…" : "Upload"}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            className="hidden"
            disabled={uploadDisabled}
            onChange={(e) => handleFileChosen(e.target.files?.[0])}
          />
        </label>
      </div>

      {uploadsUnavailable && (
        <div
          role="alert"
          className="mb-3 rounded-md border border-border bg-paper px-3 py-2 text-xs text-ink-muted"
        >
          File uploads aren't available on this server. This is a deployment
          configuration issue, not a problem with your account or project.{" "}
          <button
            type="button"
            onClick={() => {
              setUploadsUnavailable(false);
              setUploadError(null);
            }}
            className="underline hover:text-accent"
          >
            Try again
          </button>
        </div>
      )}

      {uploadError && !uploadsUnavailable && (
        <p
          role="alert"
          className="mb-3 rounded-md bg-danger-soft px-3 py-1.5 text-xs text-danger"
        >
          {uploadError}
        </p>
      )}

      {rowError && (
        <p
          role="alert"
          className="mb-3 rounded-md bg-danger-soft px-3 py-1.5 text-xs text-danger"
        >
          {rowError}
        </p>
      )}

      {loading ? (
        <LoadingRow label="Loading documents…" />
      ) : loadError ? (
        <ErrorRow message={loadError} onRetry={refresh} />
      ) : documents.length === 0 ? (
        <EmptyRow label="No documents uploaded yet." />
      ) : (
        <ul className="space-y-2">
          {documents.map((doc) => {
            const downloading = downloadingId === doc.id;
            const deleting = deletingId === doc.id;
            const busy = downloading || deleting;
            return (
              <li
                key={doc.id}
                aria-busy={busy}
                className={`flex items-center justify-between gap-3 rounded-md border border-border bg-surface p-3 ${
                  busy ? "opacity-70" : ""
                }`}
              >
                <div className="flex min-w-0 items-start gap-2">
                  <FileText size={16} className="mt-0.5 shrink-0 text-ink-faint" aria-hidden="true" />
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
                    type="button"
                    onClick={() => handleDownload(doc)}
                    disabled={busy}
                    aria-label={`Download ${doc.filename}`}
                    className="rounded-md p-2.5 text-ink-faint hover:bg-paper hover:text-ink disabled:opacity-50"
                  >
                    <Download size={15} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(doc)}
                    disabled={busy}
                    aria-label={`Delete ${doc.filename}`}
                    className="rounded-md p-2.5 text-ink-faint hover:bg-danger-soft hover:text-danger disabled:opacity-50"
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}