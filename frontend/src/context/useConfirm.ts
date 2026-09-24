import { useContext } from "react";
import { ConfirmContext } from "./confirm-context";
import type { ConfirmFn } from "./confirm-context";

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within a ConfirmProvider");
  return ctx;
}