import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ResetPasswordPage } from "./ResetPasswordPage";

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

function renderReset(search: string) {
  return render(
    <MemoryRouter initialEntries={[`/reset-password${search}`]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/login" element={<div data-testid="login">Login</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  globalThis.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ResetPasswordPage", () => {
  it("shows the invalid state when the token is missing", () => {
    renderReset("");
    expect(screen.getByText(/this link is invalid or has expired/i)).toBeInTheDocument();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("renders the form when a token is present", () => {
    renderReset("?token=reset-xyz");
    expect(screen.getByLabelText(/^new password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm new password/i)).toBeInTheDocument();
  });

  it("validates password length locally", async () => {
    const user = userEvent.setup();
    renderReset("?token=reset-xyz");
    const pw = screen.getByLabelText(/^new password$/i) as HTMLInputElement;
    // Remove minLength to allow short input into the field, exercising the
    // inline validation message that the page also renders.
    pw.removeAttribute("minlength");
    await user.type(pw, "short");
    expect(screen.getByText(/password must be at least 12 characters/i)).toBeInTheDocument();
  });

  it("validates confirmation matches", async () => {
    const user = userEvent.setup();
    renderReset("?token=reset-xyz");
    await user.type(screen.getByLabelText(/^new password$/i), "a-strong-password-12");
    await user.type(screen.getByLabelText(/confirm new password/i), "different-password-12");
    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
  });

  it("submits to /api/auth/password-reset/complete and navigates to /login", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse({ message: "Password updated." }),
    );

    const user = userEvent.setup();
    renderReset("?token=reset-xyz");
    await user.type(screen.getByLabelText(/^new password$/i), "a-strong-password-12");
    await user.type(screen.getByLabelText(/confirm new password/i), "a-strong-password-12");
    await user.click(screen.getByRole("button", { name: /update password/i }));

    await waitFor(() => expect(screen.getByTestId("login")).toBeInTheDocument());

    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/auth/password-reset/complete");
    expect(JSON.parse(init.body as string)).toEqual({
      token: "reset-xyz",
      new_password: "a-strong-password-12",
    });
  });

  it("displays the backend error on an invalid token", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse(
        { error: { code: 400, message: "This link is invalid or has expired.", request_id: null } },
        { status: 400 },
      ),
    );

    const user = userEvent.setup();
    renderReset("?token=bad");
    await user.type(screen.getByLabelText(/^new password$/i), "a-strong-password-12");
    await user.type(screen.getByLabelText(/confirm new password/i), "a-strong-password-12");
    await user.click(screen.getByRole("button", { name: /update password/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/this link is invalid or has expired/i);
    });
  });

  it("never places the password into the URL", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse({ message: "Password updated." }),
    );

    const user = userEvent.setup();
    renderReset("?token=reset-xyz");
    await user.type(screen.getByLabelText(/^new password$/i), "a-strong-password-12");
    await user.type(screen.getByLabelText(/confirm new password/i), "a-strong-password-12");
    await user.click(screen.getByRole("button", { name: /update password/i }));

    await waitFor(() => expect(screen.getByTestId("login")).toBeInTheDocument());
    expect(window.location.search).not.toContain("a-strong-password-12");
  });
});