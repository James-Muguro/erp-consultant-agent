import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { InboxItem } from "../types";
import { InboxItemRow } from "../components/inbox/InboxItem";
import { EmptyRow, ErrorRow, LoadingRow } from "../components/workspace/shared";
import { useInboxCount } from "../hooks/useInboxCount";

type View = "pending" | "history";

export function InboxPage() {
  const [view, setView] = useState<View>("pending");
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);
  const { count: pendingCount, refresh: refreshCount } = useInboxCount();

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res =
        view === "pending"
          ? await api.getInbox()
          : await api.getInboxHistory();
      setItems(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load inbox.");
    } finally {
      setLoading(false);
    }
  }, [view]);

  // Initial / view-switch load. Deferred past the effect's sync phase.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled) return;
      setLoading(true);
      setError(null);
      try {
        const res =
          view === "pending"
            ? await api.getInbox()
            : await api.getInboxHistory();
        if (!cancelled) setItems(res.items);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load inbox.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [view]);

  async function resolve(itemId: string) {
    setActing(itemId);
    try {
      await api.resolveInboxItem(itemId);
      window.dispatchEvent(new Event("inbox-changed"));
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not resolve item.");
    } finally {
      setActing(null);
    }
  }

  async function retry() {
    // Refresh both the item list and the header count so a transient
    // failure does not leave either surface stale.
    await Promise.all([reload(), refreshCount()]);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <header className="flex items-baseline justify-between gap-3">
        <div>
          <h1 className="font-display text-lg text-ink">Inbox</h1>
          <p className="mt-1 text-xs text-ink-muted">
            Actionable items routed to you. Open an item to jump into the
            workflow that owns it; resolve it once that workflow is complete.
          </p>
        </div>
        {pendingCount > 0 && (
          <span
            className="shrink-0 rounded-full bg-accent px-2 py-0.5 text-xs font-medium text-white"
            aria-label={`${pendingCount} pending items`}
          >
            {pendingCount}
          </span>
        )}
      </header>

      <nav className="flex gap-1 border-b border-border">
        {(["pending", "history"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            className={`px-3 py-2 text-sm border-b-2 -mb-px ${
              view === v
                ? "border-accent text-accent-strong"
                : "border-transparent text-ink-muted hover:text-ink"
            }`}
          >
            {v === "pending" ? "Pending" : "History"}
          </button>
        ))}
      </nav>

      {error && <ErrorRow message={error} onRetry={retry} />}

      {loading ? (
        <LoadingRow label="Loading inbox…" />
      ) : !error && items.length === 0 ? (
        <EmptyRow
          label={
            view === "pending"
              ? "Nothing pending."
              : "No resolved items yet."
          }
        />
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <InboxItemRow
              key={item.id}
              item={item}
              onResolve={view === "pending" ? resolve : undefined}
              busy={acting === item.id}
            />
          ))}
        </ul>
      )}
    </div>
  );
}