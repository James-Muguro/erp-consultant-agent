import { Check, Loader2 } from "lucide-react";
import type { AgentActivityStep } from "../hooks/useChat";

/**
 * Live progress indicator for an in-flight turn. Renders the sequence of
 * `agent_started` / `tool_started` / `tool_completed` / `workflow_completed`
 * events emitted by the backend's SSE stream, so the user sees what the
 * system is doing rather than a generic spinner.
 *
 * `role="status"` + `aria-live="polite"` cause each state change to be
 * announced to assistive technology, matching the visual behavior.
 */
export function AgentActivity({ steps }: { steps: AgentActivityStep[] }) {
  if (steps.length === 0) return null;

  return (
    <ul
      role="status"
      aria-live="polite"
      aria-label="Agent activity"
      className="space-y-1.5 rounded-md border border-border bg-accent-soft/60 px-3 py-2.5 text-sm"
    >
      {steps.map((step) => (
        <li key={step.key} className="flex items-center gap-2">
          {step.done ? (
            <Check size={14} className="shrink-0 text-accent" aria-hidden="true" />
          ) : (
            <Loader2
              size={14}
              className="shrink-0 animate-spin text-ink-muted"
              aria-hidden="true"
            />
          )}
          <span className={step.done ? "text-ink-muted" : "text-ink"}>
            {step.label}
          </span>
        </li>
      ))}
    </ul>
  );
}