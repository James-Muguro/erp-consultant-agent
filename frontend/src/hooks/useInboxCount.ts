import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/useAuth";
import { useCapabilities } from "../auth/useCapabilities";

const POLL_INTERVAL_MS = 60_000;

/**
 * Pending attention item count for the current user's inbox.
 *
 * Refreshes on mount, on window focus, on the `inbox-changed` event, and
 * on a 60-second interval while the caller holds `inbox:read`. The
 * interval exists so the badge stays current when the user is on a page
 * that does not itself re-mount the inbox — without it, a new item
 * arriving while the tab stays open and in focus would not be visible
 * until the next focus cycle.
 *
 * The window-scoped `inbox-changed` event remains the immediate path
 * after a resolve. The interval is a slow backstop, not a substitute.
 */
export function useInboxCount() {
  const { user } = useAuth();
  const capabilities = useCapabilities();
  const canRead = capabilities.can("inbox:read");
  const [count, setCount] = useState(0);

  const refresh = useCallback(async () => {
    if (!user || !canRead) {
      setCount(0);
      return;
    }
    try {
      const res = await api.getInboxCount();
      setCount(res.pending);
    } catch {
      // Silent: the badge is not security-critical and a transient
      // failure should not spam the console.
    }
  }, [user, canRead]);

  // Initial load. Deferred past the effect's sync phase so the plugin's
  // set-state-in-effect rule is satisfied; refresh() above stays for
  // the event and interval listeners below.
  useEffect(() => {
    if (!user || !canRead) return;   // count stays at its initial 0
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled) return;
      try {
        const res = await api.getInboxCount();
        if (!cancelled) setCount(res.pending);
      } catch {
        // Silent.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, canRead]);

  useEffect(() => {
    if (!canRead) return;
    const handler = () => refresh();
    window.addEventListener("focus", handler);
    window.addEventListener("inbox-changed", handler);
    const interval = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => {
      window.removeEventListener("focus", handler);
      window.removeEventListener("inbox-changed", handler);
      window.clearInterval(interval);
    };
  }, [canRead, refresh]);

  return { count, refresh };
}