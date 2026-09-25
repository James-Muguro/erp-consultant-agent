import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { VerifyEmailPage } from "./VerifyEmailPage";

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

function renderVerify(search: string) {
  return render(
    <MemoryRouter initialEntries={[`/verify-email${search}`]}>
      <Routes>
        <Route path="/verify-email" element={<VerifyEmailPage />} />
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

describe("VerifyEmailPage", () => {
  it("reads the token from the URL and calls /api/auth/verify-email", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse({ message: "Email verified." }),
    );

    renderVerify("?token=abc123");

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/auth/verify-email");
    expect(JSON.parse(init.body as string)).toEqual({ token: "abc123" });
  });

  it("shows the success state and offers navigation to login", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse({ message: "Email verified." }),
    );

    renderVerify("?token=abc123");

    await waitFor(() => {
      expect(screen.getByText(/email verified/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: /go to sign in/i })).toBeInTheDocument();
  });

  it("shows the error state on an invalid/expired token", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makeResponse(
        { error: { code: 400, message: "This link is invalid or has expired.", request_id: null } },
        { status: 400 },
      ),
    );

    renderVerify("?token=bad");

    await waitFor(() => {
      expect(screen.getByText(/link expired/i)).toBeInTheDocument();
    });
  });

  it("shows the error state when the token is missing from the URL", async () => {
    renderVerify("");
    await waitFor(() => {
      expect(screen.getByText(/link expired/i)).toBeInTheDocument();
    });
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("resend posts the entered email to /api/auth/resend-verification", async () => {
    // Initial verify fails so the resend form is rendered.
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(
        makeResponse({ error: { code: 400, message: "Invalid.", request_id: null } }, { status: 400 }),
      )
      .mockResolvedValueOnce(
        makeResponse({ message: "If an account with that email exists..." }),
      );

    const user = userEvent.setup();
    renderVerify("?token=bad");

    await waitFor(() => expect(screen.getByText(/link expired/i)).toBeInTheDocument());

    await user.type(screen.getByPlaceholderText(/you@company.com/i), "a@b.com");
    await user.click(screen.getByRole("button", { name: /resend verification email/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    });
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[1];
    expect(url).toBe("/api/auth/resend-verification");
    expect(JSON.parse(init.body as string)).toEqual({ email: "a@b.com" });

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        /if an account with that email exists/i,
      );
    });
  });
});