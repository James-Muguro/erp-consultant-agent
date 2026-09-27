import { NavLink, Navigate, useLocation, useParams } from "react-router-dom";
import type { ReactNode } from "react";
import { useArtifactGrants } from "../../hooks/useArtifactGrants";
import { QuestionnaireView } from "./QuestionnaireView";
import { FrdView } from "./FrdView";
import { UatView } from "./UatView";
import { TrainingView } from "./TrainingView";
import { SupportView } from "./SupportView";

interface ArtifactDef {
  key: string;
  label: string;
  path: string;
  view: ReactNode;
  /** When true, the tab is shown to any ERP User with at least one
   *  active grant, regardless of which artifacts they hold. */
  anyGrant?: boolean;
}

const ARTIFACTS: ArtifactDef[] = [
  {
    key: "requirements_questionnaire",
    label: "Questionnaire",
    path: "questionnaire",
    view: <QuestionnaireView />,
  },
  {
    key: "frd",
    label: "FRD",
    path: "frd",
    view: <FrdView />,
  },
  {
    key: "uat_scenarios",
    label: "UAT scenarios",
    path: "uat-scenarios",
    view: <UatView />,
  },
  {
    key: "training_materials",
    label: "Training materials",
    path: "training-materials",
    view: <TrainingView />,
  },
  {
    key: "support",
    label: "Support",
    path: "support",
    view: <SupportView />,
    anyGrant: true,
  },
];

export function ErpUserWorkspace() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const { grants, loading } = useArtifactGrants(sessionId);

  const granted = new Set(grants.map((g) => g.artifact_type));
  const hasAnyGrant = grants.length > 0;
  const visibleTabs = ARTIFACTS.filter((a) =>
    a.anyGrant ? hasAnyGrant : granted.has(a.key),
  );

  // The route paths are flat (/erp/p/:sessionId and five literal child
  // paths), so there is no nesting and no <Outlet /> to render. The
  // current artifact is the last non-empty URL segment; the workspace
  // root is the segment equal to sessionId itself.
  const segments = location.pathname.split("/").filter(Boolean);
  const suffix = segments.length > 0 ? segments[segments.length - 1] : "";
  const isRoot = suffix === sessionId;

  if (!sessionId) {
    return (
      <div className="p-6 text-sm text-ink-muted">
        Project not available.
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-6 text-sm text-ink-muted">Loading…</div>
    );
  }

  if (isRoot) {
    const first = visibleTabs[0];
    if (first) {
      return (
        <Navigate to={`/erp/p/${sessionId}/${first.path}`} replace />
      );
    }
    return (
      <div className="p-6 text-sm text-ink-muted">
        You do not currently have access to any artifacts on this project.
      </div>
    );
  }

  const current = ARTIFACTS.find((a) => a.path === suffix);

  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-medium text-ink">Project artifacts</h1>
        <p className="mt-1 text-xs text-ink-faint">
          You have access to the artifacts granted to you by the project’s
          functional consultant.
        </p>
      </header>
      <nav className="border-b border-border bg-surface px-6">
        <ul className="flex gap-1 overflow-x-auto">
          {visibleTabs.map((a) => (
            <li key={a.key}>
              <NavLink
                to={`/erp/p/${sessionId}/${a.path}`}
                className={({ isActive }) =>
                  `inline-block border-b-2 px-3 py-3 text-sm ${
                    isActive
                      ? "border-accent text-accent-strong"
                      : "border-transparent text-ink-muted hover:text-ink"
                  }`
                }
              >
                {a.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="p-6">
        {current ? (
          current.view
        ) : (
          <p className="text-sm text-ink-muted">
            This artifact is not available on this project.
          </p>
        )}
      </main>
    </div>
  );
}