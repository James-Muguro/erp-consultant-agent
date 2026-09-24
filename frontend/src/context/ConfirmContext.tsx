import { useCallback, useState, type ReactNode } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ConfirmContext } from "./confirm-context";
import type { ConfirmFn, ConfirmOptions } from "./confirm-context";

interface PendingConfirm {
  options: ConfirmOptions;
  resolve: (confirmed: boolean) => void;
}

/**
 * Provides `useConfirm()` to the app. The dialog is rendered once, at
 * the provider, regardless of how many confirmations are requested; a
 * queue is used rather than a "last request wins" state so concurrent
 * callers each receive their own boolean result.
 */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<PendingConfirm[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const current = queue[0] ?? null;

  const confirm = useCallback<ConfirmFn>((options) => {
    return new Promise<boolean>((resolve) => {
      setQueue((q) => [...q, { options, resolve }]);
    });
  }, []);

  const popCurrent = useCallback((confirmed: boolean) => {
    setQueue((q) => {
      const [first, ...rest] = q;
      first?.resolve(confirmed);
      return rest;
    });
    setError(null);
  }, []);

  const handleConfirm = useCallback(async () => {
    if (!current) return;
    const onConfirm = current.options.onConfirm;
    if (!onConfirm) {
      popCurrent(true);
      return;
    }
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      popCurrent(true);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Something went wrong.",
      );
    } finally {
      setPending(false);
    }
  }, [current, popCurrent]);

  const handleCancel = useCallback(() => {
    if (pending) return;
    popCurrent(false);
  }, [pending, popCurrent]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <ConfirmDialog
        open={current !== null}
        title={current?.options.title ?? ""}
        description={current?.options.description}
        confirmLabel={current?.options.confirmLabel ?? "Confirm"}
        cancelLabel={current?.options.cancelLabel ?? "Cancel"}
        variant={current?.options.variant ?? "default"}
        pending={pending}
        error={error}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </ConfirmContext.Provider>
  );
}