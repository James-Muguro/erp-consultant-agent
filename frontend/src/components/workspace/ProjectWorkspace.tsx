import { useState } from "react";
import { HealthOverview } from "./HealthOverview";
import { RequirementsList } from "./RequirementsList";
import { ProcessStepsList } from "./ProcessStepsList";
import { SolutionDecisionsList } from "./SolutionDecisionsList";
import { TestingTrainingList } from "./TestingTrainingList";
import { IssuesList } from "./IssuesList";
import { UploadsPanel } from "./UploadsPanel";

type Tab = "overview" | "requirements" | "process" | "solution" | "testing" | "issues" | "documents";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "requirements", label: "Requirements" },
  { id: "process", label: "Process steps" },
  { id: "solution", label: "Solution decisions" },
  { id: "testing", label: "Testing & training" },
  { id: "issues", label: "Issues" },
  { id: "documents", label: "Documents" },
];

export function ProjectWorkspace({ sessionId }: { sessionId: string }) {
  const [tab, setTab] = useState<Tab>("overview");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <nav
        role="tablist"
        aria-label="Project sections"
        className="flex gap-1 overflow-x-auto border-b border-border bg-surface px-3 py-2 sm:px-4"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`shrink-0 rounded-md px-3 py-2 text-sm transition-colors sm:py-1.5 ${
              tab === t.id ? "bg-accent-soft text-accent-strong" : "text-ink-muted hover:bg-paper"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto max-w-3xl" role="tabpanel">
          {tab === "overview" && <HealthOverview sessionId={sessionId} />}
          {tab === "requirements" && <RequirementsList sessionId={sessionId} />}
          {tab === "process" && <ProcessStepsList sessionId={sessionId} />}
          {tab === "solution" && <SolutionDecisionsList sessionId={sessionId} />}
          {tab === "testing" && <TestingTrainingList sessionId={sessionId} />}
          {tab === "issues" && <IssuesList sessionId={sessionId} />}
          {tab === "documents" && <UploadsPanel sessionId={sessionId} />}
        </div>
      </div>
    </div>
  );
}
