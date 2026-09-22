import { Link, useParams } from "react-router-dom";
import { HealthOverview } from "./HealthOverview";
import { RequirementsList } from "./RequirementsList";
import { ProcessStepsList } from "./ProcessStepsList";
import { SolutionDecisionsList } from "./SolutionDecisionsList";
import { TestingTrainingList } from "./TestingTrainingList";
import { IssuesList } from "./IssuesList";
import { UploadsPanel } from "./UploadsPanel";
import { DeliverablesPanel } from "./DeliverablesPanel";

type Tab =
  | "overview"
  | "requirements"
  | "process"
  | "solution"
  | "testing"
  | "issues"
  | "deliverables"
  | "documents";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "requirements", label: "Requirements" },
  { id: "process", label: "Process steps" },
  { id: "solution", label: "Solution decisions" },
  { id: "testing", label: "Testing & training" },
  { id: "issues", label: "Issues" },
  { id: "deliverables", label: "Deliverables" },
  { id: "documents", label: "Uploads" },
];

function isTab(value: string | undefined): value is Tab {
  return value !== undefined && TABS.some((t) => t.id === value);
}

export function ProjectWorkspace({ sessionId }: { sessionId: string }) {
  const { tab: rawTab } = useParams<{ tab?: string }>();
  const tab: Tab = isTab(rawTab) ? rawTab : "overview";

  function tabPath(id: Tab): string {
    return id === "overview" ? `/p/${sessionId}` : `/p/${sessionId}/${id}`;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <nav
        role="tablist"
        aria-label="Project sections"
        className="flex gap-1 overflow-x-auto border-b border-border bg-surface px-3 py-2 sm:px-4"
      >
        {TABS.map((t) => {
          const isActive = tab === t.id;
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

      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto max-w-3xl" role="tabpanel">
          {tab === "overview" && <HealthOverview sessionId={sessionId} />}
          {tab === "requirements" && <RequirementsList sessionId={sessionId} />}
          {tab === "process" && <ProcessStepsList sessionId={sessionId} />}
          {tab === "solution" && <SolutionDecisionsList sessionId={sessionId} />}
          {tab === "testing" && <TestingTrainingList sessionId={sessionId} />}
          {tab === "issues" && <IssuesList sessionId={sessionId} />}
          {tab === "deliverables" && <DeliverablesPanel sessionId={sessionId} />}
          {tab === "documents" && <UploadsPanel sessionId={sessionId} />}
        </div>
      </div>
    </div>
  );
}