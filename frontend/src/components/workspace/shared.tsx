import type { ReactNode } from "react";
import type { IssueSeverity, ReviewStatus } from "../../types";

export function WorkspaceCard({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="font-display text-base text-ink">{title}</h3>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

export function EmptyRow({ label }: { label: string }) {
  return <p className="py-6 text-center text-sm text-ink-faint">{label}</p>;
}

const STATUS_STYLES: Record<ReviewStatus, string> = {
  draft: "bg-paper text-ink-muted border-border",
  approved: "bg-accent-soft text-accent-strong border-accent",
  rejected: "bg-danger-soft text-danger border-danger",
};

export function StatusBadge({ status }: { status: ReviewStatus }) {
  return (
    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status] ?? STATUS_STYLES.draft}`}>
      {status}
    </span>
  );
}

const SEVERITY_STYLES: Record<IssueSeverity, string> = {
  high: "bg-danger-soft text-danger border-danger",
  medium: "bg-paper text-ink-muted border-border-strong",
  low: "bg-paper text-ink-faint border-border",
};

export function SeverityBadge({ severity }: { severity: IssueSeverity }) {
  return (
    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.low}`}>
      {severity}
    </span>
  );
}

export function LinkedRequirementBadge({ requirementId }: { requirementId: string | null }) {
  if (!requirementId) {
    return <span className="text-xs text-ink-faint">Not yet linked to a requirement</span>;
  }
  return (
    <span className="rounded-sm bg-accent-soft px-1.5 py-0.5 font-mono text-xs text-accent-strong">
      req: {requirementId.slice(0, 8)}
    </span>
  );
}
