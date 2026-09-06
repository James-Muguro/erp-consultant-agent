import { useState, type FormEvent } from "react";
import { X } from "lucide-react";

const MODULES = ["FI", "MM", "SD", "HCM", "PP", "QM"];

export function NewProjectModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (name: string, module: string, erpSystem: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [module, setModule] = useState("FI");
  const [erpSystem, setErpSystem] = useState("SAP S/4HANA");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      await onCreate(name.trim(), module, erpSystem);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 px-4">
      <div className="w-full max-w-md rounded-md border border-border bg-surface p-6 shadow-lg">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-xl text-ink">New project</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm text-ink-muted">Project name</label>
            <input
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Procure-to-Pay rollout"
              className="w-full rounded-md border border-border bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-sm text-ink-muted">Module</label>
              <select
                value={module}
                onChange={(e) => setModule(e.target.value)}
                className="w-full rounded-md border border-border bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              >
                {MODULES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm text-ink-muted">ERP system</label>
              <input
                value={erpSystem}
                onChange={(e) => setErpSystem(e.target.value)}
                className="w-full rounded-md border border-border bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-accent py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
          >
            {submitting ? "Creating…" : "Create project"}
          </button>
        </form>
      </div>
    </div>
  );
}
