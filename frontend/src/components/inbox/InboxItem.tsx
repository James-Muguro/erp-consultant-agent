import { Link } from "react-router-dom";
import type { InboxItem } from "../../types";

const SOURCE_LABEL: Record<string, string> = {
  bid_won: "Bid won",
  developer_completion_issue: "Issue",
  developer_completion_test_case: "Test case",
  erp_user_request: "Request",
};

function sourceLabel(sourceType: string): string {
  return (
    SOURCE_LABEL[sourceType] ??
    sourceType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export function InboxItemRow({
  item,
  onResolve,
  busy,
}: {
  item: InboxItem;
  onResolve?: (id: string) => void;
  busy?: boolean;
}) {
  const body = (
    <>
      <span className="inline-block rounded-sm bg-accent-soft px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent-strong">
        {sourceLabel(item.source_type)}
      </span>
      <p className="mt-1.5 text-sm text-ink">
        {item.title ?? item.source_type.replace(/_/g, " ")}
      </p>
      {item.subtitle && (
        <p className="mt-0.5 text-xs text-ink-muted">{item.subtitle}</p>
      )}
      <p className="mt-1 text-xs text-ink-faint">
        {item.created_at ? new Date(item.created_at).toLocaleString() : ""}
        {item.status === "resolved" && item.resolved_at && (
          <> · resolved {new Date(item.resolved_at).toLocaleString()}</>
        )}
      </p>
    </>
  );

  return (
    <li className="rounded-md border border-border bg-surface hover:border-accent">
      <div className="flex items-start justify-between gap-3 p-3">
        {item.context_url ? (
          <Link to={item.context_url} className="min-w-0 flex-1">
            {body}
          </Link>
        ) : (
          <div className="min-w-0 flex-1">{body}</div>
        )}
        {onResolve && item.status === "pending" && (
          <button
            type="button"
            onClick={() => onResolve(item.id)}
            disabled={busy}
            className="shrink-0 rounded-md border border-border px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-accent-strong disabled:opacity-50"
          >
            {busy ? "Resolving…" : "Resolve"}
          </button>
        )}
      </div>
    </li>
  );
}