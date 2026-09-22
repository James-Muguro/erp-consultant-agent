import { ArrowRight } from "lucide-react";
import type { NextAction } from "../types";

/**
 * Shown once, at the top of a freshly created project's chat, in place
 * of the generic empty state. The action is the backend's real
 * `next_action` from `POST /api/projects/start` - this component never
 * invents a workflow step.
 *
 * If the user refreshes before acting, `next_action` is gone (it is only
 * returned by the create endpoint and by SSE message_complete events).
 * In that case the generic EmptyState is shown instead. That is
 * deliberate: re-deriving a "next step" on the frontend from
 * ProjectStatus would be manufacturing workflow state, which is exactly
 * what we are avoiding.
 *
 * Clicking the button sends the button's own label as a message via the
 * normal chat pipeline. That is not fabrication - the user took the
 * action, and the backend's conversation history will faithfully record
 * it as such.
 */
export function ProjectStartCard({
  action,
  onStart,
  disabled,
}: {
  action: NextAction;
  onStart: (agentHint: string, label: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <p className="text-xs uppercase tracking-wider text-ink-faint">
        Ready to begin
      </p>
      <p className="mt-3 max-w-md text-sm text-ink-muted">
        This project has no messages yet. The next step below is set by the
        workflow — or you can ask a question directly.
      </p>
      <button
        type="button"
        onClick={() => onStart(action.agent_hint, action.label)}
        disabled={disabled}
        className="mt-6 inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
      >
        {action.label}
        <ArrowRight size={14} aria-hidden="true" />
      </button>
    </div>
  );
}