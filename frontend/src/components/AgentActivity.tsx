import { Check, Loader2 } from "lucide-react";
import type { AgentActivityStep } from "../hooks/useChat";

export function AgentActivity({ steps }: { steps: AgentActivityStep[] }) {
  if (steps.length === 0) return null;

  return (
    <ul className="space-y-1.5 rounded-md border border-border bg-accent-soft/60 px-3 py-2.5 text-sm">
      {steps.map((step) => (
        <li key={step.key} className="flex items-center gap-2">
          {step.done ? (
            <Check size={14} className="shrink-0 text-accent" />
          ) : (
            <Loader2 size={14} className="shrink-0 animate-spin text-ink-muted" />
          )}
          <span className={step.done ? "text-ink-muted" : "text-ink"}>{step.label}</span>
        </li>
      ))}
    </ul>
  );
}
