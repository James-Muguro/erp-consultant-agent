import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  clearToken,
  getToken,
  onAuthExpired,
  readCsrfToken,
  setToken,
  CSRF_COOKIE_NAME,
  CSRF_HEADER_NAME,
} from "./client";
import type { SignupPayload, User } from "../types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function makeResponse(
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
): Response {
  const status = init.status ?? 200;
  const headers = new Headers(init.headers ?? {});
  if (!headers.has("Content-Type") && body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
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

function mockFetchOnce(response: Response) {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(response);
}

function readCall(index = 0): { url: string; init: RequestInit } {
  const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
  const [url, init] = calls[index] as [string, RequestInit];
  return { url, init };
}

function headersOf(init: RequestInit): Headers {
  return new Headers(init.headers);
}

function setCsrfCookie(value: string) {
  document.cookie = `${CSRF_COOKIE_NAME}=${encodeURIComponent(value)}; path=/`;
}

function clearAllCookies() {
  for (const c of document.cookie.split(";")) {
    const name = c.split("=")[0].trim();
    if (name) {
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
    }
  }
}

const SAMPLE_USER: User = {
  id: "u-1",
  email: "a@b.com",
  name: null,
  profile_picture_url: null,
  created_at: "2026-01-01T00:00:00Z",
  roles: ["developer"],
  organizations: [],
};

beforeEach(() => {
  globalThis.fetch = vi.fn();
  localStorage.clear();
  clearAllCookies();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Signup
// ---------------------------------------------------------------------------
describe("api.signup", () => {
  const payload: SignupPayload = {
    email: "a@b.com",
    password: "correct horse battery staple",
    account_type: "developer",
  };

  it("POSTs the payload to /api/auth/signup and returns MessageResponse", async () => {
    mockFetchOnce(makeResponse({ message: "If this email address can be registered..." }));

    const result = await api.signup(payload);

    const { url, init } = readCall();
    expect(url).toBe("/api/auth/signup");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(payload);
    expect(init.credentials).toBe("include");
    expect(result).toEqual({ message: "If this email address can be registered..." });
  });

  it("does NOT attach Authorization even when a token is stored", async () => {
    setToken("stale-token");
    mockFetchOnce(makeResponse({ message: "ok" }));

    await api.signup(payload);

    const { init } = readCall();
    expect(headersOf(init).get("Authorization")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Login (two-step)
// ---------------------------------------------------------------------------
describe("api.initiateLogin", () => {
  it("POSTs to /api/auth/login and returns the pending-auth response", async () => {
    mockFetchOnce(
      makeResponse({
        pending_auth_ref: "ref-abc",
        expires_in_minutes: 10,
        message: "A sign-in code has been sent.",
      }),
    );

    const result = await api.initiateLogin("a@b.com", "password-value-12");

    const { url, init } = readCall();
    expect(url).toBe("/api/auth/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@b.com",
      password: "password-value-12",
    });
    // The response must NOT contain access_token / refresh_token.
    expect(result).not.toHaveProperty("access_token");
    expect(result.pending_auth_ref).toBe("ref-abc");
  });

  it("does NOT attach Authorization on /login", async () => {
    setToken("stale");
    mockFetchOnce(makeResponse({ pending_auth_ref: "r", expires_in_minutes: 10, message: "ok" }));
    await api.initiateLogin("a@b.com", "password-value-12");
    expect(headersOf(readCall().init).get("Authorization")).toBeNull();
  });
});

describe("api.verifyOtp", () => {
  it("POSTs the pending-auth ref and code; returns TokenResponse", async () => {
    mockFetchOnce(makeResponse({ access_token: "new-token", token_type: "bearer", expires_in_minutes: 15 }));

    const result = await api.verifyOtp("ref-abc", "123456");

    const { url, init } = readCall();
    expect(url).toBe("/api/auth/login/verify-otp");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      pending_auth_ref: "ref-abc",
      code: "123456",
    });
    expect(result.access_token).toBe("new-token");
    expect(init.credentials).toBe("include");
  });
});

describe("api.resendOtp", () => {
  it("POSTs the pending-auth ref to /api/auth/login/resend-otp", async () => {
    mockFetchOnce(makeResponse({ pending_auth_ref: "ref-abc", expires_in_minutes: 10, message: "ok" }));

    await api.resendOtp("ref-abc");

    const { url, init } = readCall();
    expect(url).toBe("/api/auth/login/resend-otp");
    expect(JSON.parse(init.body as string)).toEqual({ pending_auth_ref: "ref-abc" });
  });
});

// ---------------------------------------------------------------------------
// Email verification
// ---------------------------------------------------------------------------
describe("api.verifyEmail", () => {
  it("POSTs the token to /api/auth/verify-email", async () => {
    mockFetchOnce(makeResponse({ message: "Email verified." }));
    const result = await api.verifyEmail("token-xyz");
    const { url, init } = readCall();
    expect(url).toBe("/api/auth/verify-email");
    expect(JSON.parse(init.body as string)).toEqual({ token: "token-xyz" });
    expect(result).toEqual({ message: "Email verified." });
  });
});

describe("api.resendVerification", () => {
  it("POSTs the email to /api/auth/resend-verification", async () => {
    mockFetchOnce(makeResponse({ message: "If an account with that email exists..." }));
    await api.resendVerification("a@b.com");
    const { url, init } = readCall();
    expect(url).toBe("/api/auth/resend-verification");
    expect(JSON.parse(init.body as string)).toEqual({ email: "a@b.com" });
  });
});

// ---------------------------------------------------------------------------
// Refresh and CSRF
// ---------------------------------------------------------------------------
describe("api.refresh", () => {
  it("POSTs to /api/auth/refresh with credentials: include", async () => {
    setCsrfCookie("csrf-1");
    mockFetchOnce(makeResponse({ access_token: "t1", token_type: "bearer", expires_in_minutes: 15 }));
    await api.refresh();
    const { url, init } = readCall();
    expect(url).toBe("/api/auth/refresh");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
  });

  it("sends X-CSRF-Token from the current document.cookie", async () => {
    setCsrfCookie("csrf-value-1");
    mockFetchOnce(makeResponse({ access_token: "t1", token_type: "bearer", expires_in_minutes: 15 }));
    await api.refresh();
    expect(headersOf(readCall().init).get(CSRF_HEADER_NAME)).toBe("csrf-value-1");
  });

  it("reads CSRF fresh on each call — no caching across refreshes", async () => {
    setCsrfCookie("csrf-1");
    mockFetchOnce(makeResponse({ access_token: "t1", token_type: "bearer", expires_in_minutes: 15 }));
    await api.refresh();

    // The backend rotates the CSRF cookie on success. Simulate by
    // updating the cookie, then calling refresh again.
    setCsrfCookie("csrf-2");
    mockFetchOnce(makeResponse({ access_token: "t2", token_type: "bearer", expires_in_minutes: 15 }));
    await api.refresh();

    expect(headersOf(readCall(0).init).get(CSRF_HEADER_NAME)).toBe("csrf-1");
    expect(headersOf(readCall(1).init).get(CSRF_HEADER_NAME)).toBe("csrf-2");
  });

  it("omits the CSRF header when no CSRF cookie is present", async () => {
    mockFetchOnce(makeResponse({ error: { code: 401, message: "Session expired.", request_id: null } }, { status: 401 }));
    await expect(api.refresh()).rejects.toBeInstanceOf(ApiError);
    expect(headersOf(readCall().init).get(CSRF_HEADER_NAME)).toBeNull();
  });

  it("does NOT attach Authorization on /refresh", async () => {
    setToken("some-token");
    setCsrfCookie("csrf-1");
    mockFetchOnce(makeResponse({ access_token: "t", token_type: "bearer", expires_in_minutes: 15 }));
    await api.refresh();
    expect(headersOf(readCall().init).get("Authorization")).toBeNull();
  });
});

describe("readCsrfToken", () => {
  it("returns null when the CSRF cookie is absent", () => {
    expect(readCsrfToken()).toBeNull();
  });

  it("reads only the CSRF cookie, not the refresh cookie", () => {
    document.cookie = `erp_refresh_token=must-not-be-read; path=/`;
    setCsrfCookie("csrf-value");
    expect(readCsrfToken()).toBe("csrf-value");
  });

  it("decodes URI-encoded values", () => {
    setCsrfCookie("a/b+c=");
    expect(readCsrfToken()).toBe("a/b+c=");
  });
});

// ---------------------------------------------------------------------------
// Logout
// ---------------------------------------------------------------------------
describe("api.logout", () => {
  it("POSTs to /api/auth/logout with the current CSRF header", async () => {
    setCsrfCookie("csrf-logout");
    mockFetchOnce(makeResponse({ message: "Signed out." }));

    await api.logout();

    const { url, init } = readCall();
    expect(url).toBe("/api/auth/logout");
    expect(init.method).toBe("POST");
    expect(headersOf(init).get(CSRF_HEADER_NAME)).toBe("csrf-logout");
    expect(init.credentials).toBe("include");
  });

  it("omits the CSRF header when no CSRF cookie is present", async () => {
    mockFetchOnce(makeResponse({ message: "Signed out." }));
    await api.logout();
    expect(headersOf(readCall().init).get(CSRF_HEADER_NAME)).toBeNull();
  });
});

describe("api.logoutAll", () => {
  it("POSTs to /api/auth/logout-all with Authorization", async () => {
    setToken("access-token");
    mockFetchOnce(makeResponse({ message: "Signed out of all devices." }));

    await api.logoutAll();

    const { url, init } = readCall();
    expect(url).toBe("/api/auth/logout-all");
    expect(init.method).toBe("POST");
    expect(headersOf(init).get("Authorization")).toBe("Bearer access-token");
  });
});

// ---------------------------------------------------------------------------
// Password reset
// ---------------------------------------------------------------------------
describe("api.requestPasswordReset", () => {
  it("POSTs the email to /api/auth/password-reset/request", async () => {
    mockFetchOnce(makeResponse({ message: "If an account with that email exists..." }));
    await api.requestPasswordReset("a@b.com");
    const { url, init } = readCall();
    expect(url).toBe("/api/auth/password-reset/request");
    expect(JSON.parse(init.body as string)).toEqual({ email: "a@b.com" });
  });
});

describe("api.completePasswordReset", () => {
  it("POSTs token + new_password to /api/auth/password-reset/complete", async () => {
    mockFetchOnce(makeResponse({ message: "Password updated." }));
    await api.completePasswordReset("reset-token", "new-password-1234");
    const { url, init } = readCall();
    expect(url).toBe("/api/auth/password-reset/complete");
    expect(JSON.parse(init.body as string)).toEqual({
      token: "reset-token",
      new_password: "new-password-1234",
    });
  });
});

// ---------------------------------------------------------------------------
// Authorization header behavior
// ---------------------------------------------------------------------------
describe("Authorization header", () => {
  it("attaches the stored token to /api/auth/me", async () => {
    setToken("access-token");
    mockFetchOnce(makeResponse(SAMPLE_USER));
    await api.me();
    expect(headersOf(readCall().init).get("Authorization")).toBe("Bearer access-token");
  });

  it("does not attach a token when none is stored", async () => {
    mockFetchOnce(makeResponse(SAMPLE_USER));
    await api.me();
    expect(headersOf(readCall().init).get("Authorization")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// onAuthExpired
// ---------------------------------------------------------------------------
describe("onAuthExpired", () => {
  it("fires when a protected request returns 401", async () => {
    const handler = vi.fn();
    const unsub = onAuthExpired(handler);
    try {
      setToken("bad");
      mockFetchOnce(makeResponse({ error: { code: 401, message: "Expired.", request_id: null } }, { status: 401 }));
      await expect(api.me()).rejects.toBeInstanceOf(ApiError);
      expect(handler).toHaveBeenCalledTimes(1);
      // The stored token is cleared by the signal.
      expect(getToken()).toBeNull();
    } finally {
      unsub();
    }
  });

  it.each([
    ["/api/auth/signup", () => api.signup({ email: "a@b.com", password: "correct horse battery staple", account_type: "developer" })],
    ["/api/auth/login", () => api.initiateLogin("a@b.com", "password-value-12")],
    ["/api/auth/login/verify-otp", () => api.verifyOtp("r", "123456")],
    ["/api/auth/login/resend-otp", () => api.resendOtp("r")],
    ["/api/auth/verify-email", () => api.verifyEmail("t")],
    ["/api/auth/resend-verification", () => api.resendVerification("a@b.com")],
    ["/api/auth/password-reset/request", () => api.requestPasswordReset("a@b.com")],
    ["/api/auth/password-reset/complete", () => api.completePasswordReset("t", "new-password-1234")],
    ["/api/auth/refresh", () => api.refresh()],
  ])("does NOT fire from %s", async (_path, call) => {
    const handler = vi.fn();
    const unsub = onAuthExpired(handler);
    try {
      mockFetchOnce(makeResponse({ error: { code: 401, message: "Nope.", request_id: null } }, { status: 401 }));
      await expect(call()).rejects.toBeInstanceOf(ApiError);
      expect(handler).not.toHaveBeenCalled();
    } finally {
      unsub();
    }
  });
});

// ---------------------------------------------------------------------------
// ApiError parsing
// ---------------------------------------------------------------------------
describe("ApiError parsing", () => {
  it("reads the {error: {code, message, request_id}} envelope", async () => {
    mockFetchOnce(
      makeResponse(
        { error: { code: 400, message: "Invalid or expired code.", request_id: "req-123" } },
        { status: 400 },
      ),
    );
    try {
      await api.verifyOtp("r", "000000");
      throw new Error("expected ApiError");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const e = err as ApiError;
      expect(e.status).toBe(400);
      expect(e.kind).toBe("validation");
      expect(e.message).toBe("Invalid or expired code.");
      expect(e.requestId).toBe("req-123");
    }
  });

  it("handles the FastAPI validation detail array (422)", async () => {
    mockFetchOnce(
      makeResponse(
        { detail: [{ loc: ["body", "code"], msg: "code must be 6 digits", type: "value_error" }] },
        { status: 422 },
      ),
    );
    await expect(api.verifyOtp("r", "abc")).rejects.toMatchObject({
      status: 422,
      kind: "validation",
    });
  });

  it("handles the slowapi string form and preserves Retry-After", async () => {
    mockFetchOnce(
      makeResponse(
        { error: "Rate limit exceeded: 5 per 1 minute" },
        { status: 429, headers: { "Retry-After": "60" } },
      ),
    );
    await expect(
      api.signup({ email: "a@b.com", password: "correct horse battery staple", account_type: "developer" }),
    ).rejects.toMatchObject({ status: 429, kind: "rate_limit", retryAfterSeconds: 60 });
  });
});

// Cleanup
afterEach(() => {
  clearToken();
});