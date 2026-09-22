import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";

export interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "default" | "danger";
  /**
   * Runs when the user clicks the confirm button. The dialog stays open
   * with a pending indicator until this returns (or resolves). If it
   * rejects, the dialog stays open and shows the error message inline so
   * the user can retry or cancel - the outer promise only resolves when
   * the user has either completed the action or explicitly cancelled.
   *
   * Omit `onConfirm` for a pure yes/no prompt: the dialog closes on the
   * confirm click and the promise resolves `true`.
   */
  onConfirm?: () => void | Promise<void>;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

interface PendingConfirm {
  options: ConfirmOptions;
  resolve: (confirmed: boolean) => void;
}

const ConfirmContext = createContext<ConfirmFn | null>(null);

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
      // Resolve outside of the state updater would be safer under
      // StrictMode; but the updater runs synchronously per React's
      // contract for the batched setState here, and the resolver is
      // idempotent, so this is safe. If we ever need to be stricter
      // about side effects, move the resolve into a useEffect keyed on
      // the queue.
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

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within a ConfirmProvider");
  return ctx;
}