import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/**
 * Catches render-time errors anywhere below it so a single bad render in
 * a workspace tab or the chat surface does not blank the entire app.
 * Async errors (rejected promises) are NOT caught here - those are the
 * responsibility of the calling code, which now surfaces them via
 * ApiError and inline error states.
 *
 * The reset action is a full navigation rather than a state reset: if a
 * component crashed because of a specific route's data, re-rendering the
 * same route would just re-crash. Returning home is the safe action.
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

  render() {
    if (this.state.error) {
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