import { Link, useOutletContext } from "react-router-dom";
import { Plus } from "lucide-react";
import { useAuth } from "../context/useAuth";
import { useCapabilities } from "../auth/useCapabilities";

type OutletCtx = { refreshProjects: () => Promise<void> };

/**
 * Landing route. Shown to every authenticated user regardless of
 * capability. Content adapts:
 *   - the ad-hoc chat CTA is only offered to users who can use chat,
 *   - the welcome text mentions organizations when the user has any,
 *     so an organization-only account sees a coherent entry point.
 */
export function ProjectListRoute() {
  const _ctx = useOutletContext<OutletCtx>();
  void _ctx;

  const { user } = useAuth();
  const capabilities = useCapabilities();
  const canChat = capabilities.can("chat:submit");
  const hasOrganizations = (user?.organizations.length ?? 0) > 0;

  return (
    <div className="mx-auto flex max-w-2xl flex-1 flex-col items-center justify-center px-6 py-16 text-center">
      <h1 className="font-display text-2xl text-ink">Welcome to Tarzyna</h1>
      <p className="mt-3 max-w-md text-sm text-ink-muted">
        {hasOrganizations
          ? "Select an organization from the sidebar to manage it, or open a project to continue."
          : "Pick a project from the sidebar to open its workspace, or start a new one to begin a structured ERP engagement."}
      </p>
      {canChat && (
        <Link
          to="/chat"
          className="mt-6 inline-flex items-center gap-2 rounded-md border border-border px-4 py-2 text-sm text-ink-muted hover:border-accent hover:text-accent"
        >
          <Plus size={14} />
          Start an ad-hoc chat
        </Link>
      )}
    </div>
  );
}