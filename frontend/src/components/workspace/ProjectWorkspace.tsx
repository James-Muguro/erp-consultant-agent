import { Link, useParams } from "react-router-dom";
import { ErrorBoundary } from "../../routes/ErrorBoundary";
import { NotAuthorizedState } from "../../routes/NotAuthorizedState";
import { useCapabilities } from "../../auth/useCapabilities";
import type { Permission } from "../../auth/capabilities";
import { HealthOverview } from "./HealthOverview";
import { RequirementsList } from "./RequirementsList";
import { ProcessStepsList } from "./ProcessStepsList";
import { SolutionDecisionsList } from "./SolutionDecisionsList";
import { TestingTrainingList } from "./TestingTrainingList";
import { IssuesList } from "./IssuesList";
import { UploadsPanel } from "./UploadsPanel";
import { DeliverablesPanel } from "./DeliverablesPanel";
import { TeamAccessTab } from "./TeamAccessTab";
import { SupportTab } from "./SupportTab";

/**
 * Project workspace.
 *
 * The overall workspace route is gated on phase:execute by RequireAuth
 * via routeConfig. This component gates the individual tabs on their
 * respective read capabilities, so a role that can enter the workspace
 * but cannot use a specific section sees only the tabs it can use.
 *
 * phase:execute as the workspace-entry capability is a Phase 2.2
 * decision. The backend does not currently expose a dedicated
 * workspace-entry capability. phase:execute is the intersection of the
 * Functional Consultant and Developer capability sets and excludes
 * Business Development and ERP User — matching the locked role scope.
 *
 * ERP Users do NOT reach this component. Their artifact surface lives
 * under /erp/p/*, gated on RequireArtifactGrant and per-endpoint
 * backend authorization. The phase:execute gate on /p/* is not
 * relaxed; the ERP User experience is a separate route tree.
 */

type Tab =
  | "overview"
  | "requirements"
  | "process"
  | "solution"
  | "testing"
  | "issues"
  | "support"
  | "deliverables"
  | "documents"
  | "team-access";

const TABS: { id: Tab; label: string; capability: Permission }[] = [
  { id: "overview", label: "Overview", capability: "health:read" },
  { id: "requirements", label: "Requirements", capability: "requirements:read" },
  { id: "process", label: "Process steps", capability: "process_steps:read" },
  { id: "solution", label: "Solution decisions", capability: "solution:read" },
  { id: "testing", label: "Testing & training", capability: "testing:read" },
  { id: "issues", label: "Issues", capability: "issues:read" },
  { id: "support", label: "Support", capability: "issues:read" },
  { id: "deliverables", label: "Deliverables", capability: "documents:read" },
  { id: "documents", label: "Uploads", capability: "uploads:read" },
  { id: "team-access", label: "Team access", capability: "project:grants:manage" },
];

function isTab(value: string | undefined): value is Tab {
  return value !== undefined && TABS.some((t) => t.id === value);
}

function TabBodyError({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-1 items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-md border border-border bg-surface p-6 text-center">
        <h2 className="font-display text-lg text-ink">
          This tab couldn't be displayed
        </h2>
        <p className="mt-2 text-sm text-ink-muted">
          Something went wrong while rendering this section. You can
          switch to another tab, or try again.
        </p>
        {error.message && (
          <p className="mt-3 break-words rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
            {error.message}
          </p>
        )}
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
        >
          Try again
        </button>
      </div>
    </div>
  );
}

export function ProjectWorkspace({ sessionId }: { sessionId: string }) {
  const { tab: rawTab } = useParams<{ tab?: string }>();
  const capabilities = useCapabilities();

  // The visible tab set is the intersection of all tabs with the
  // capabilities the caller actually holds. Computed on every render;
  // useCapabilities is memoized on the user object, so this is cheap.
  const visibleTabs = TABS.filter((t) => capabilities.can(t.capability));

  // Defensive: a workspace participant should always have at least one
  // authorized tab. If not, render the not-authorized state rather than
  // an empty workspace with no content.
  if (visibleTabs.length === 0) {
    return (
      <NotAuthorizedState
        title="No workspace sections available"
        description="Your account doesn't have access to any project workspace sections."
        backTo="/"
      />
    );
  }

  // Determine which tab the URL requests and whether it is authorized.
  const requestedTab: Tab | null = isTab(rawTab) ? rawTab : null;
  const requestedTabConfig = requestedTab
    ? TABS.find((t) => t.id === requestedTab)!
    : null;
  const requestedIsDenied =
    requestedTabConfig !== null &&
    !capabilities.can(requestedTabConfig.capability);

  // Fallback when the URL has no explicit (or a mismatched) tab.
  const fallbackTab: Tab = visibleTabs[0].id;
  const activeTab: Tab = requestedTab ?? fallbackTab;

  function tabPath(id: Tab): string {
    return id === "overview" ? `/p/${sessionId}` : `/p/${sessionId}/${id}`;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <nav
        role="tablist"
        aria-label="Project sections"
        className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-surface px-3 py-2 sm:px-4"
      >
        {visibleTabs.map((t) => {
          const isActive = !requestedIsDenied && activeTab === t.id;
          return (
            <Link
              key={t.id}
              to={tabPath(t.id)}
              role="tab"
              aria-selected={isActive}
              className={`shrink-0 rounded-md px-3 py-2 text-sm transition-colors sm:py-1.5 ${
                isActive
                  ? "bg-accent-soft text-accent-strong"
                  : "text-ink-muted hover:bg-paper"
              }`}
            >
              {t.label}
            </Link>
          );
        })}
      </nav>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 sm:p-6">
        <ErrorBoundary
          key={`${sessionId}-${activeTab}-${requestedIsDenied}`}
          fallback={(error, reset) => (
            <TabBodyError error={error} onRetry={reset} />
          )}
        >
          <div className="mx-auto max-w-3xl" role="tabpanel">
            {requestedIsDenied ? (
              <NotAuthorizedState
                inline
                title="You don't have access to this section"
                description="Your account doesn't have the permissions required to view this project section."
              />
            ) : (
              <>
                {activeTab === "overview" && <HealthOverview sessionId={sessionId} />}
                {activeTab === "requirements" && (
                  <RequirementsList sessionId={sessionId} />
                )}
                {activeTab === "process" && (
                  <ProcessStepsList sessionId={sessionId} />
                )}
                {activeTab === "solution" && (
                  <SolutionDecisionsList sessionId={sessionId} />
                )}
                {activeTab === "testing" && (
                  <TestingTrainingList sessionId={sessionId} />
                )}
                {activeTab === "issues" && <IssuesList sessionId={sessionId} />}
                {activeTab === "support" && <SupportTab sessionId={sessionId} />}
                {activeTab === "deliverables" && (
                  <DeliverablesPanel sessionId={sessionId} />
                )}
                {activeTab === "documents" && (
                  <UploadsPanel sessionId={sessionId} />
                )}
                {activeTab === "team-access" && (
                  <TeamAccessTab sessionId={sessionId} />
                )}
              </>
            )}
          </div>
        </ErrorBoundary>
      </div>
    </div>
  );
}