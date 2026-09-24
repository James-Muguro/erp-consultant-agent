import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

/**
 * A component that throws on render when `shouldThrow` is true and
 * renders a stable marker otherwise.
 */
function Bomb({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("boom");
  return <div>children rendered</div>;
}

describe("ErrorBoundary", () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;
  const originalLocation = window.location;

  beforeEach(() => {
    // React logs caught render errors via console.error. Silence it
    // so the test output stays readable; this does not affect behavior.
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    // jsdom does not allow assignment to window.location.href directly.
    // Install a spyable plain object so the default fallback's hard
    // navigation can be asserted.
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: { href: "" },
    });
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: originalLocation,
    });
  });

  // ------------------------------------------------------------------
  // Default (unconfigured) behavior — must be preserved for the root
  // boundary in main.tsx.
  // ------------------------------------------------------------------
  it("renders children when no error is thrown", () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("children rendered")).toBeInTheDocument();
  });

  it("renders the default full-screen fallback when a child throws", () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Return home" }),
    ).toBeInTheDocument();
  });

  it("default fallback navigates to / on click", () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Return home" }));
    expect(window.location.href).toBe("/");
  });

  // ------------------------------------------------------------------
  // Scoped fallback — used by AppLayout and ProjectWorkspace.
  // ------------------------------------------------------------------
  it("renders the custom fallback when supplied", () => {
    render(
      <ErrorBoundary
        fallback={(error, reset) => (
          <div>
            <span>custom fallback: {error.message}</span>
            <button onClick={reset}>recover</button>
          </div>
        )}
      >
        <Bomb shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("custom fallback: boom")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "recover" }),
    ).toBeInTheDocument();
  });

  it("custom fallback's reset re-mounts children after the error is cleared", () => {
    function Wrapper() {
      const [throwing, setThrowing] = useState(true);
      return (
        <ErrorBoundary
          fallback={(_error, reset) => (
            <button
              onClick={() => {
                setThrowing(false);
                reset();
              }}
            >
              recover
            </button>
          )}
        >
          <Bomb shouldThrow={throwing} />
        </ErrorBoundary>
      );
    }
    render(<Wrapper />);
    fireEvent.click(screen.getByRole("button", { name: "recover" }));
    expect(screen.getByText("children rendered")).toBeInTheDocument();
  });
});