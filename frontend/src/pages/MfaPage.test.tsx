import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { MfaPage } from "./MfaPage";
import { AuthContext, type AuthContextValue } from "../context/auth-context";
import { ApiError } from "../api/client";

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

function makeContext(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    user: null,
    loading: false,
    verifyOtp: vi.fn(),
    updateAccountSettings: vi.fn(),
    uploadProfilePicture: vi.fn(),
    changePassword: vi.fn(),
    deleteAccount: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    ...overrides,
  };
}

function renderMfa(state: unknown, ctx: AuthContextValue = makeContext()) {
  return render(
    <AuthContext.Provider value={ctx}>
      <MemoryRouter initialEntries={[{ pathname: "/mfa", state }]}>
        <Routes>
          <Route path="/mfa" element={<MfaPage />} />
          <Route path="/" element={<div data-testid="home">Home</div>} />
          <Route path="/login" element={<div data-testid="login">Login</div>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

beforeEach(() => {
  globalThis.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MfaPage", () => {
  it("rejects missing navigation state cleanly", () => {
    renderMfa(null);
    expect(screen.getByText(/sign-in expired/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to sign in/i })).toBeInTheDocument();
  });

  it("renders the code input when a pending-auth ref is present", () => {
    renderMfa({ pendingAuthRef: "ref-abc" });
    expect(screen.getByLabelText(/verification code/i)).toBeInTheDocument();
  });

  it("submits the OTP via verifyOtp and navigates to /", async () => {
    const verifyOtp = vi.fn().mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    renderMfa({ pendingAuthRef: "ref-abc" }, makeContext({ verifyOtp }));

    await user.type(screen.getByLabelText(/verification code/i), "123456");
    await user.click(screen.getByRole("button", { name: /verify and sign in/i }));

    await waitFor(() => expect(screen.getByTestId("home")).toBeInTheDocument());
    expect(verifyOtp).toHaveBeenCalledWith("ref-abc", "123456");
  });

  it("shows the backend error on invalid OTP", async () => {
    const verifyOtp = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError({ status: 400, kind: "validation", message: "Invalid or expired code." }),
      );
    const user = userEvent.setup();
    renderMfa({ pendingAuthRef: "ref-abc" }, makeContext({ verifyOtp }));

    await user.type(screen.getByLabelText(/verification code/i), "000000");
    await user.click(screen.getByRole("button", { name: /verify and sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid or expired code.");
    });
  });

  it("resend calls POST /api/auth/login/resend-otp with the pending ref", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse({ pending_auth_ref: "ref-abc", expires_in_minutes: 10, message: "..." }),
    );
    const user = userEvent.setup();
    renderMfa({ pendingAuthRef: "ref-abc" });

    await user.click(screen.getByRole("button", { name: /resend code/i }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/auth/login/resend-otp");
    expect(JSON.parse(init.body as string)).toEqual({ pending_auth_ref: "ref-abc" });
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/if this sign-in is still pending/i);
    });
  });

  it("does not store the pending-auth ref anywhere JS-accessible", async () => {
    const verifyOtp = vi.fn().mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    renderMfa({ pendingAuthRef: "ref-abc" }, makeContext({ verifyOtp }));

    await user.type(screen.getByLabelText(/verification code/i), "123456");
    await user.click(screen.getByRole("button", { name: /verify and sign in/i }));

    await waitFor(() => expect(screen.getByTestId("home")).toBeInTheDocument());

    // The pending ref must never appear in localStorage or sessionStorage.
    for (const store of [localStorage, sessionStorage]) {
      for (let i = 0; i < store.length; i++) {
        const key = store.key(i)!;
        expect(store.getItem(key)).not.toContain("ref-abc");
      }
    }
  });
});