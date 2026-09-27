import { Link } from "react-router-dom";
import { ShieldAlert } from "lucide-react";

/**
 * Shared forbidden / not-authorized state.
 *
 * Two variants:
 *
 *   - Full-screen (default): rendered by RequireAuth when the caller
 *     lacks the capability required by the current route. Replaces the
 *     AppLayout shell entirely — the user was trying to reach a page
 *     they cannot use, so collapsing the chrome is the correct signal.
 *
 *   - Inline (`inline`): rendered inside an already-rendered shell
 *     (e.g. the ProjectWorkspace body when the current tab is not
 *     authorized). Keeps the surrounding chrome visible so the user can
 *     navigate to a tab they can access.
 *
 * No role strings appear here; the component is purely presentational.
 */
export function NotAuthorizedState({
  title = "You don't have access to this section",
  description = "Your account doesn't have the permissions required to view this page.",
  backTo = "/",
  backLabel = "Back to home",
  inline = false,
}: {
  title?: string;
  description?: string;
  backTo?: string;
  backLabel?: string;
  inline?: boolean;
}) {
  const body = (
    <>
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-paper text-ink-muted">
        <ShieldAlert size={20} aria-hidden="true" />
      </div>
      <h2 className="font-display text-lg text-ink">{title}</h2>
      <p className="mt-2 text-sm text-ink-muted">{description}</p>
      {!inline && (
        <Link
          to={backTo}
          className="mt-4 inline-block rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
        >
          {backLabel}
        </Link>
      )}
    </>
  );

  if (inline) {
    return (
      <div role="alert" className="py-12 text-center">
        {body}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <div className="w-full max-w-md rounded-md border border-border bg-surface p-6 text-center">
        {body}
      </div>
    </div>
  );
}