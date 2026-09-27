import { useParams } from "react-router-dom";
import { Building2 } from "lucide-react";
import { useAuth } from "../context/useAuth";
import { useCapabilities } from "../auth/useCapabilities";
import { NotAuthorizedState } from "../routes/NotAuthorizedState";
import { WorkspaceCard } from "../components/workspace/shared";

/**
 * Organization context entry point.
 *
 * This is the placeholder dashboard introduced by Phase 2.2. It exists
 * so the organization-context navigation model has a destination to
 * route to, and so the nine locked organization capabilities have a
 * visible "coming soon" surface. It does NOT implement any of those
 * capabilities; they belong to their own later scope.
 *
 * What this page does implement:
 *   - resolves the current org from the URL against the caller's
 *     memberships,
 *   - renders a coherent not-authorized state if the caller is not a
 *     member (or the URL references a non-existent org),
 *   - surfaces the caller's role and privileges in that org.
 *
 * Organization context is additive: entering it does not remove the
 * caller's application-role navigation. The sidebar keeps showing the
 * application experience; this page renders inside the same shell.
 */

const ORG_CAPABILITY_GRID: { key: string; label: string; blurb: string }[] = [
  { key: "dashboard", label: "Dashboard", blurb: "Organization overview and recent activity." },
  { key: "members", label: "Members", blurb: "People who belong to this organization." },
  { key: "invitations", label: "Invitations", blurb: "Pending invites and their status." },
  { key: "roles", label: "Role assignment", blurb: "Assign organization roles to members." },
  { key: "visibility", label: "Project visibility", blurb: "Control who sees which projects." },
  { key: "projects", label: "Organization projects", blurb: "Projects owned by this organization." },
  { key: "analytics", label: "Cross-project analytics", blurb: "Trends across the firm's engagements." },
  { key: "knowledge", label: "Firm knowledge base", blurb: "Reusable firm-level knowledge (placeholder)." },
  { key: "billing", label: "Billing & subscription", blurb: "Plan, usage, and billing (placeholder)." },
];

export function OrganizationDashboardPage() {
  const { orgId } = useParams<{ orgId: string }>();
  const { user } = useAuth();
  const capabilities = useCapabilities();

  if (!orgId) {
    return (
      <NotAuthorizedState
        title="Organization not available"
        description="This organization link is invalid."
      />
    );
  }

  const org = user?.organizations.find((o) => o.id === orgId);
  if (!org || !capabilities.isInOrganization(orgId)) {
    return (
      <NotAuthorizedState
        title="Organization not available"
        description="You are not a member of this organization, or it no longer exists."
      />
    );
  }

  const canManageMembers = capabilities.canInOrganization(orgId, "org:member:manage");
  const canManageSettings = capabilities.canInOrganization(orgId, "org:settings:edit");

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
        <header className="mb-6 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-accent-soft text-accent-strong">
            <Building2 size={20} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h1 className="font-display text-2xl text-ink truncate">
              {org.name}
            </h1>
            <p className="text-xs text-ink-muted">
              Organization context · your role: {org.role}
              {canManageMembers ? " · member management" : ""}
              {canManageSettings ? " · settings" : ""}
            </p>
          </div>
        </header>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {ORG_CAPABILITY_GRID.map((cap) => (
            <WorkspaceCard key={cap.key} title={cap.label}>
              <p className="text-sm text-ink-muted">{cap.blurb}</p>
              <p className="mt-2 text-xs text-ink-faint">Coming soon.</p>
            </WorkspaceCard>
          ))}
        </div>
      </div>
    </div>
  );
}