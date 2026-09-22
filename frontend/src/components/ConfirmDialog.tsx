import { useEffect, useRef } from "react";
import { AlertTriangle } from "lucide-react";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel: string;
  cancelLabel: string;
  variant: "default" | "danger";
  /** True while `onConfirm` from the caller is in flight. Disables both
   * buttons so the user cannot double-trigger or navigate away mid-action. */
  pending: boolean;
  /** Error surfaced when `onConfirm` rejected. Kept local to the dialog
   * so a failed confirmation never closes into a state where the user
   * cannot tell whether the action succeeded. */
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Presentational confirmation dialog. Used exclusively via the
 * promise-based `useConfirm` hook (see ConfirmContext). Renders as an
 * alertdialog because it interrupts a flow that the user has already
 * initiated - not a passive informational dialog.
 *
 * Behavior:
 *   - Escape cancels (ignored while pending).
 *   - Backdrop click cancels (ignored while pending).
 *   - Focus moves into the dialog on open, is trapped while it is
 *     mounted, and returns to the previously focused element on close.
 *   - The Cancel button receives focus by default; for a destructive
 *     action that is the safer default.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel,
  variant,
  pending,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    cancelButtonRef.current?.focus();

    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        if (!pending) onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      const root = dialogRef.current;
      if (!root) return;
      const focusable = Array.from(
        root.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      previouslyFocused?.focus?.();
    };
  }, [open, pending, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-ink/40 p-4"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget && !pending) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby={description ? "confirm-dialog-description" : undefined}
        className="w-full max-w-sm rounded-md border border-border bg-surface p-5 shadow-lg"
      >
        {variant === "danger" && (
          <div className="mb-3 flex items-center gap-2 text-danger">
            <AlertTriangle size={15} aria-hidden="true" />
            <span className="text-xs font-medium uppercase tracking-wide">
              Destructive action
            </span>
          </div>
        )}
        <h2 id="confirm-dialog-title" className="font-display text-lg text-ink">
          {title}
        </h2>
        {description && (
          <p
            id="confirm-dialog-description"
            className="mt-2 text-sm text-ink-muted"
          >
            {description}
          </p>
        )}
        {error && (
          <p
            role="alert"
            className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            ref={cancelButtonRef}
            type="button"
            onClick={onCancel}
            disabled={pending}
            className="rounded-md border border-border-strong px-4 py-2 text-sm font-medium text-ink-muted transition-colors hover:bg-paper disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className={`rounded-md px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-60 ${
              variant === "danger"
                ? "bg-danger hover:brightness-95"
                : "bg-accent hover:bg-accent-strong"
            }`}
          >
            {pending ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}