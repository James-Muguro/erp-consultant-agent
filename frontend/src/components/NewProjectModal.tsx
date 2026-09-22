import { useEffect, useState, type FormEvent } from "react";
import { X } from "lucide-react";

/**
 * The module list is curated for an ERP consulting engagement, not for a
 * specific ERP vendor. Labels are what the user picks; the underlying
 * values are what gets sent to `POST /api/projects/start` as `module`.
 *
 * The backend's intent classifier extracts modules from chat as free
 * text (e.g. "FI", "financials", "MM"), so the stored value is a label
 * of convenience, not a foreign key. This list mirrors the terminology
 * the sidebar and workspace use elsewhere in the app so nothing looks
 * inconsistent across surfaces.
 *
 * "Other" is included because ERP engagements regularly span domains
 * that don't fit a fixed taxonomy (regulatory, industry-specific,
 * multi-module integrations). Requiring the user to pick from a closed
 * list would misrepresent a real project.
 */
const MODULE_OPTIONS = [
  { value: "Finance", label: "Finance & Accounting" },
  { value: "Procurement", label: "Procurement & Materials" },
  { value: "Sales", label: "Sales & Distribution" },
  { value: "Supply Chain", label: "Supply Chain" },
  { value: "Manufacturing", label: "Manufacturing & Production" },
  { value: "HCM", label: "Human Capital" },
  { value: "CRM", label: "Customer Relationship" },
  { value: "Analytics", label: "Analytics & Reporting" },
  { value: "Integration", label: "Integration & Platform" },
] as const;

const OTHER_VALUE = "__other__";

export function NewProjectModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (name: string, module: string, erpSystem: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [moduleChoice, setModuleChoice] = useState<string>("");
  const [moduleOther, setModuleOther] = useState("");
  const [erpSystem, setErpSystem] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isOther = moduleChoice === OTHER_VALUE;
  const effectiveModule = isOther ? moduleOther.trim() : moduleChoice;

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || !effectiveModule) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreate(name.trim(), effectiveModule, erpSystem.trim());
    } catch (err) {
      // Previously the modal had no error path: a failed create left the
      // modal open with no explanation, and the error propagated as an
      // unhandled rejection.
      setError(
        err instanceof Error ? err.message : "Could not create project.",
      );
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
            <label
              htmlFor="new-project-name"
              className="mb-1 block text-sm text-ink-muted"
            >
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
            <label
              htmlFor="new-project-module"
              className="mb-1 block text-sm text-ink-muted"
            >
              Primary module
            </label>
            <select
              id="new-project-module"
              required
              value={moduleChoice}
              onChange={(e) => setModuleChoice(e.target.value)}
              className="w-full rounded-md border border-border bg-paper px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
            >
              <option value="" disabled>
                Select a module…
              </option>
              {MODULE_OPTIONS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
              <option value={OTHER_VALUE}>Other…</option>
            </select>
            {isOther && (
              <input
                required
                value={moduleOther}
                onChange={(e) => setModuleOther(e.target.value)}
                placeholder="Describe the module or domain"
                maxLength={32}
                className="mt-2 w-full rounded-md border border-border bg-paper px-3 py-2.5 text-base text-ink outline-none focus:border-accent sm:text-sm"
              />
            )}
            <p className="mt-1 text-xs text-ink-faint">
              This shows on the project in the sidebar. You can ask the
              assistant to work across other modules later.
            </p>
          </div>

          <div>
            <label
              htmlFor="new-project-erp"
              className="mb-1 block text-sm text-ink-muted"
            >
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

          {error && (
            <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}

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
              disabled={submitting || !name.trim() || !effectiveModule}
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