import type { ReactNode } from "react";
import type { IssueSeverity, ReviewStatus } from "../../types";

export function WorkspaceCard({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
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

export function LoadingRow({ label }: { label: string }) {
  return (
    <p role="status" aria-live="polite" className="py-6 text-center text-sm text-ink-faint">
      {label}
    </p>
  );
}

export function ErrorRow({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="py-6 text-center text-sm">
      <p className="text-danger">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 text-xs text-ink-muted underline hover:text-accent"
        >
          Try again
        </button>
      )}
    </div>
  );
}

const STATUS_STYLES: Record<ReviewStatus, string> = {
  draft: "bg-paper text-ink-muted border-border-strong",
  approved: "bg-accent-soft text-accent-strong border-accent",
  rejected: "bg-danger-soft text-danger border-danger",
};

export function StatusBadge({ status }: { status: ReviewStatus }) {
  return (
    <span
      className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[status] ?? STATUS_STYLES.draft
      }`}
    >
      {status}
    </span>
  );
}

/**
 * Severity tiers, ordered visually. Previously medium and low both used
 * a neutral border and were nearly indistinguishable at a glance; medium
 * now uses the warning tier (amber-on-cream) so the three levels are
 * clearly ordered from the user's perspective.
 */
const SEVERITY_STYLES: Record<IssueSeverity, string> = {
  high: "bg-danger-soft text-danger border-danger",
  medium: "bg-warning-soft text-warning border-warning",
  low: "bg-paper text-ink-muted border-border-strong",
};

export function SeverityBadge({ severity }: { severity: IssueSeverity }) {
  return (
    <span
      className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${
        SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.low
      }`}
    >
      {severity}
    </span>
  );
}

export function LinkedRequirementBadge({
  requirementId,
}: {
  requirementId: string | null;
}) {
  if (!requirementId) {
    return (
      <span className="text-xs text-ink-faint">
        Not yet linked to a requirement
      </span>
    );
  }
  return (
    <span className="rounded-sm bg-accent-soft px-1.5 py-0.5 font-mono text-xs text-accent-strong">
      req: {requirementId.slice(0, 8)}
    </span>
  );
}