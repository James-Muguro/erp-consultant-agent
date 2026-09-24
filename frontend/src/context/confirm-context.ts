import { createContext } from "react";

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

export type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

export const ConfirmContext = createContext<ConfirmFn | null>(null);