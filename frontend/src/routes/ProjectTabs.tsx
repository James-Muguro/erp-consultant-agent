import { LayoutGrid, MessageSquare } from "lucide-react";
import { Link, useMatch } from "react-router-dom";

/**
 * Workspace / Chat toggle shown above the project content area. Active
 * state is derived from the URL, not from local state - that is the whole
 * point of the router migration.
 */
export function ProjectTabs({ sessionId }: { sessionId: string }) {
  const isChatTab = Boolean(useMatch("/p/:sessionId/chat"));

  const base =
    "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-2 text-sm transition-colors md:py-1.5";
  const active = "bg-accent-soft text-accent-strong";
  const inactive = "text-ink-muted hover:bg-paper";

  return (
    <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-surface px-3 py-2 md:px-4">
      <Link
        to={`/p/${sessionId}`}
        className={`${base} ${isChatTab ? inactive : active}`}
      >
        <LayoutGrid size={14} />
        Workspace
      </Link>
      <Link
        to={`/p/${sessionId}/chat`}
        className={`${base} ${isChatTab ? active : inactive}`}
      >
        <MessageSquare size={14} />
        Chat
      </Link>
    </div>
  );
}