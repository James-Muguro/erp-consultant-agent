import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /**
   * Optional scoped fallback. When provided, the boundary renders this
   * function's return value instead of the default full-screen UI on a
   * caught error.
   *
   * `reset` clears the boundary's error state so the children re-mount;
   * it does not navigate. Scoped uses supply their own recovery UI
   * (typically a "Try again" button that calls reset()).
   */
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches render-time errors anywhere below it.
 *
 * At the root (see main.tsx) it renders a full-screen fallback with a
 * hard navigation back to "/" — that recovers from a broken route or a
 * data shape the app cannot render at all.
 *
 * Scoped uses (route content in AppLayout, tab body in
 * ProjectWorkspace) supply a `fallback` render prop and are keyed by
 * the caller (e.g. `key={location.pathname}` or `key={tab}`). A change
 * of context unmounts the boundary and mounts a fresh one with no
 * error state, which is the standard React reset idiom and does not
 * require any reset logic inside this component.
 *
 * Async errors (rejected promises) are NOT caught here — those are the
 * responsibility of the calling code, which surfaces them via ApiError
 * and inline error states.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // In production this should forward to an error reporting service.
    // Until then, the console is the only channel.
    console.error("Uncaught render error", error, info);
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.reset);
      }
      return (
        <div className="flex min-h-screen items-center justify-center bg-paper px-4">
          <div className="w-full max-w-md rounded-md border border-border bg-surface p-6 text-center">
            <h1 className="font-display text-xl text-ink">
              Something went wrong
            </h1>
            <p className="mt-2 text-sm text-ink-muted">
              An unexpected error occurred. Your work is saved on the server.
            </p>
            {this.state.error.message && (
              <p className="mt-3 break-words rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
                {this.state.error.message}
              </p>
            )}
            <button
              type="button"
              onClick={() => {
                this.setState({ error: null });
                window.location.href = "/";
              }}
              className="mt-4 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
            >
              Return home
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}