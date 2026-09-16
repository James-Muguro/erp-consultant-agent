import { useEffect, useState, type FormEvent } from "react";
import { X } from "lucide-react";

export function NewProjectModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (name: string, erpSystem: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [erpSystem, setErpSystem] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      await onCreate(name.trim(), erpSystem.trim());
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/30 p-4 pt-16 sm:items-center sm:pt-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-project-title"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-md border border-border bg-surface p-5 shadow-lg sm:p-6"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 id="new-project-title" className="font-display text-xl text-ink">
            New project
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="-mr-2 rounded-md p-2 text-ink-faint hover:bg-paper hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="new-project-name" className="mb-1 block text-sm text-ink-muted">
              Project name
            </label>
            <input
              id="new-project-name"
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Procure-to-Pay rollout"
              className="w-full rounded-md border border-border bg-paper px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
            />
          </div>
          <div>
            <label htmlFor="new-project-erp" className="mb-1 block text-sm text-ink-muted">
              ERP system
            </label>
            <input
              id="new-project-erp"
              value={erpSystem}
              onChange={(e) => setErpSystem(e.target.value)}
              placeholder="e.g. SAP S/4HANA, Oracle Fusion, NetSuite"
              className="w-full rounded-md border border-border bg-paper px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
            />
          </div>

          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-border px-4 py-2.5 text-sm font-medium text-ink-muted transition-colors hover:bg-paper sm:py-2"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60 sm:py-2"
            >
              {submitting ? "Creating…" : "Create project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
