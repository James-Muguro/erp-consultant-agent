import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { useOutletContext } from "react-router-dom";

type OutletCtx = { refreshProjects: () => Promise<void> };

/**
 * Landing route. The sidebar already lists every project; this page is
 * the recovery state for "nothing selected" and the discovery surface
 * for new users. Kept intentionally light - the sidebar is the primary
 * navigation, not this.
 */
export function ProjectListRoute() {
  // Wired for future use (e.g. a CTA that refreshes before showing a
  // newly created project). Kept here so the Outlet context type is
  // documented at the call site.
  const _ctx = useOutletContext<OutletCtx>();
  void _ctx;

  return (
    <div className="mx-auto flex max-w-2xl flex-1 flex-col items-center justify-center px-6 py-16 text-center">
      <h1 className="font-display text-2xl text-ink">Welcome to Tarzyna</h1>
      <p className="mt-3 max-w-md text-sm text-ink-muted">
        Pick a project from the sidebar to open its workspace, or start a
        new one to begin a structured ERP engagement.
      </p>
      <Link
        to="/chat"
        className="mt-6 inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm text-ink-muted hover:border-accent hover:text-accent"
      >
        <Plus size={14} />
        Start an ad-hoc chat
      </Link>
    </div>
  );
}