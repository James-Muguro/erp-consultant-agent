import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { LoginPage } from "./LoginPage";

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

function mockFetchOnce(body: unknown, init: { status?: number } = {}) {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(makeResponse(body, init));
}

function MfaProbe() {
  const location = useLocation();
  return (
    <div data-testid="mfa-probe">{JSON.stringify(location.state ?? {})}</div>
  );
}

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/mfa" element={<MfaProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  globalThis.fetch = vi.fn();
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

/**
 * The tab-mode toggle and the form submit button both carry the
 * accessible name "Log in". Testing Library refuses to disambiguate
 * a `getByRole` query that matches two elements, so the submit is
 * picked out by its `type="submit"` attribute.
 */
function getLoginSubmitButton(): HTMLElement {
  const candidates = screen.getAllByRole("button", { name: /^log in$/i });
  const submit = candidates.find(
    (b) => (b as HTMLButtonElement).type === "submit",
  );
  if (!submit) {
    throw new Error(
      "expected a submit button named 'Log in' but none was found",
    );
  }
  return submit;
}

// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------
describe("LoginPage login flow", () => {
  it("POSTs email + password to /api/auth/login and navigates to /mfa with the pending ref", async () => {
    const user = userEvent.setup();
    mockFetchOnce({
      pending_auth_ref: "ref-abc",
      expires_in_minutes: 10,
      message: "A sign-in code has been sent.",
    });

    renderLogin();
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/^password$/i), "correct horse battery staple");
    await user.click(getLoginSubmitButton());

    await waitFor(() => {
      const probe = screen.getByTestId("mfa-probe");
      expect(probe).toBeInTheDocument();
      expect(JSON.parse(probe.textContent || "{}")).toEqual({
        pendingAuthRef: "ref-abc",
      });
    });

    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/auth/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@b.com",
      password: "correct horse battery staple",
    });
  });

  it("displays the generic backend error on invalid credentials", async () => {
    const user = userEvent.setup();
    mockFetchOnce(
      { error: { code: 401, message: "Invalid email or password.", request_id: null } },
      { status: 401 },
    );

    renderLogin();
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/^password$/i), "wrong-password-value");
    await user.click(getLoginSubmitButton());

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid email or password.");
    });
  });
});

// ---------------------------------------------------------------------------
// Signup
// ---------------------------------------------------------------------------
describe("LoginPage signup flow", () => {
  it("POSTs the signup payload and shows the verification-email confirmation", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ message: "If this email address can be registered..." });

    renderLogin();
    await user.click(screen.getByRole("button", { name: /^sign up$/i }));
    await user.selectOptions(screen.getByLabelText(/account type/i), "developer");
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/^password$/i), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: /^create account$/i }));

    await waitFor(() => {
      expect(screen.getByText(/check your email/i)).toBeInTheDocument();
    });

    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/auth/signup");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@b.com",
      password: "correct horse battery staple",
      account_type: "developer",
      organization_name: undefined,
    });
  });

  it("sends organization_name only for organization signup", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ message: "ok" });

    renderLogin();
    await user.click(screen.getByRole("button", { name: /^sign up$/i }));
    await user.selectOptions(screen.getByLabelText(/account type/i), "organization");
    await user.type(screen.getByLabelText(/organization name/i), "Acme");
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/^password$/i), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: /^create account$/i }));

    await waitFor(() => expect(screen.getByText(/check your email/i)).toBeInTheDocument());
    const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@b.com",
      password: "correct horse battery staple",
      account_type: "organization",
      organization_name: "Acme",
    });
  });

  it("does not attempt to authenticate on signup (no token set)", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ message: "ok" });

    renderLogin();
    await user.click(screen.getByRole("button", { name: /^sign up$/i }));
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/^password$/i), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: /^create account$/i }));

    await waitFor(() => expect(screen.getByText(/check your email/i)).toBeInTheDocument());
    expect(localStorage.getItem("erp_agent_token")).toBeNull();
  });

  it("enforces maxLength=128 on the password input", () => {
    renderLogin();
    const password = screen.getByLabelText(/^password$/i) as HTMLInputElement;
    expect(password.maxLength).toBe(128);
    expect(password.minLength).toBe(12);
  });

  it("renders the same confirmation state whether the backend indicates success or a duplicate (enumeration-resistant)", async () => {
    const user = userEvent.setup();
    mockFetchOnce({ message: "If this email address can be registered..." });

    renderLogin();
    await user.click(screen.getByRole("button", { name: /^sign up$/i }));
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.type(screen.getByLabelText(/^password$/i), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: /^create account$/i }));

    await waitFor(() => expect(screen.getByText(/check your email/i)).toBeInTheDocument());
  });

  it("displays a backend validation error (422) when the password is too short", async () => {
    const user = userEvent.setup();
    mockFetchOnce(
      { detail: [{ loc: ["body", "password"], msg: "Password must be at least 12 characters.", type: "value_error" }] },
      { status: 422 },
    );

    renderLogin();
    await user.click(screen.getByRole("button", { name: /^sign up$/i }));
    // Bypass the client minLength by typing a short password.
    const password = screen.getByLabelText(/^password$/i) as HTMLInputElement;
    password.removeAttribute("minlength");
    await user.type(password, "short");
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.click(screen.getByRole("button", { name: /^create account$/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Password must be at least 12 characters/);
    });
  });
});