import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { AuthContext, type AuthContextValue } from "./context/auth-context";
import { ConfirmProvider } from "./context/ConfirmContext";
import type { User } from "./types";

const SAMPLE_USER: User = {
  id: "u-1",
  email: "a@b.com",
  name: "Alice",
  profile_picture_url: null,
  created_at: "2026-01-01T00:00:00Z",
  roles: ["developer"],
  organizations: [],
};

function makeContext(user: User | null, loading = false): AuthContextValue {
  return {
    user,
    loading,
    verifyOtp: vi.fn(),
    updateAccountSettings: vi.fn(),
    uploadProfilePicture: vi.fn(),
    changePassword: vi.fn(),
    deleteAccount: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
  };
}

/**
 * Render the full App with the two providers it needs:
 *
 *   - AuthContext, supplied directly with a fixture value rather than
 *     through AuthProvider, so tests can control `user` and `loading`
 *     without triggering the provider's bootstrap flow.
 *   - ConfirmProvider, required by AppLayout (via its useConfirm call)
 *     and by SettingsPage's danger zone. Without it, the authenticated
 *     route tree throws "useConfirm must be used within a
 *     ConfirmProvider" during render.
 *
 * MemoryRouter supplies the routing context for react-router-dom.
 */
function renderApp(path: string, ctx: AuthContextValue) {
  return render(
    <AuthContext.Provider value={ctx}>
      <ConfirmProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </ConfirmProvider>
    </AuthContext.Provider>,
  );
}

function makeResponse(body: unknown, init: { status?: number } = {}): Response {
  const status = init.status ?? 200;
  const headers = new Headers();
  if (body !== undefined) headers.set("Content-Type", "application/json");
  const text = body === undefined ? "" : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    headers,
    text: async () => text,
    json: async () => body,
    blob: async () => new Blob([text]),
  } as unknown as Response;
}

beforeEach(() => {
  // AppLayout's listProjects call resolves to an empty project list so
  // the authenticated-workspace tests do not depend on any specific
  // project fixture.
  globalThis.fetch = vi.fn(async () => makeResponse({ projects: [] }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App routing", () => {
  it("renders LoginPage at /login for an unauthenticated user", () => {
    renderApp("/login", makeContext(null));
    // Two elements carry the name "Log in" (the tab toggle and the
    // form submit). Presence-of-login-page is what this test asserts;
    // use getAllByRole to sidestep the ambiguity.
    expect(
      screen.getAllByRole("button", { name: /^log in$/i }).length,
    ).toBeGreaterThan(0);
  });

  it("redirects unauthenticated users from the workspace root to /login", () => {
    renderApp("/", makeContext(null));
    expect(
      screen.getAllByRole("button", { name: /^log in$/i }).length,
    ).toBeGreaterThan(0);
  });

  it("renders the ForgotPasswordPage without authentication", () => {
    renderApp("/forgot-password", makeContext(null));
    expect(screen.getByText(/reset your password/i)).toBeInTheDocument();
  });

  it("renders the ResetPasswordPage without authentication", () => {
    renderApp("/reset-password", makeContext(null));
    expect(screen.getByText(/this link is invalid or has expired/i)).toBeInTheDocument();
  });

  it("renders the loading state while auth is being resolved", () => {
    renderApp("/", makeContext(null, true));
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("renders the authenticated workspace at / instead of redirecting to /login", async () => {
    renderApp("/", makeContext(SAMPLE_USER));
    // AppLayout renders. The sidebar's "New chat" button is a stable
    // marker of the authenticated chrome.
    expect(
      await screen.findByRole("button", { name: /new chat/i }),
    ).toBeInTheDocument();
    // And the login form is not present.
    expect(screen.queryByLabelText(/^email$/i)).not.toBeInTheDocument();
  });

  it("redirects an authenticated user away from /login back to the workspace", async () => {
    renderApp("/login", makeContext(SAMPLE_USER));
    // The route table redirects /login to / for an authenticated user,
    // so the workspace chrome renders instead of the login form.
    expect(
      await screen.findByRole("button", { name: /new chat/i }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/^email$/i)).not.toBeInTheDocument();
  });
});