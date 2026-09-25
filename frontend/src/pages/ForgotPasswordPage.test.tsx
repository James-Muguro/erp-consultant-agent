import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ForgotPasswordPage } from "./ForgotPasswordPage";

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

function renderForgot() {
  return render(
    <MemoryRouter initialEntries={["/forgot-password"]}>
      <Routes>
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
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

describe("ForgotPasswordPage", () => {
  it("POSTs the email and shows the generic confirmation", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse({ message: "If an account with that email exists..." }),
    );

    const user = userEvent.setup();
    renderForgot();
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => {
      expect(screen.getByText(/if an account with that email exists/i)).toBeInTheDocument();
    });

    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/auth/password-reset/request");
    expect(JSON.parse(init.body as string)).toEqual({ email: "a@b.com" });
  });

  it("shows the same confirmation for an unknown email (enumeration-resistant)", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse({ message: "If an account with that email exists..." }),
    );

    const user = userEvent.setup();
    renderForgot();
    await user.type(screen.getByLabelText(/email/i), "unknown@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => {
      expect(screen.getByText(/if an account with that email exists/i)).toBeInTheDocument();
    });
  });

  it("does not put the email into the URL", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse({ message: "ok" }),
    );

    const user = userEvent.setup();
    renderForgot();
    await user.type(screen.getByLabelText(/email/i), "a@b.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(screen.getByText(/if an account with that email exists/i)).toBeInTheDocument());
    // No URL param on the page.
    expect(window.location.search).not.toContain("a@b.com");
  });
});