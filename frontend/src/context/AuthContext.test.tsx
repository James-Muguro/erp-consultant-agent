import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { AuthProvider } from "./AuthContext";
import { useAuth } from "./useAuth";
import { getToken, setToken } from "../api/client";
import type { User } from "../types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
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

function mockFetchOnce(response: Response) {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(response);
}

const SAMPLE_USER: User = {
  id: "u-1",
  email: "a@b.com",
  name: "Alice",
  profile_picture_url: null,
  created_at: "2026-01-01T00:00:00Z",
  roles: ["developer"],
  organizations: [],
};

function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

beforeEach(() => {
  globalThis.fetch = vi.fn();
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
describe("AuthProvider bootstrap", () => {
  it("starts in loading state before any promise resolves", () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation(
      () => new Promise(() => {}),
    );
    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current.loading).toBe(true);
    expect(result.current.user).toBeNull();
  });

  it("with a valid stored token: calls /me and sets the user, without refreshing", async () => {
    setToken("valid-token", 15);
    mockFetchOnce(makeResponse(SAMPLE_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user?.id).toBe("u-1");

    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls).toHaveLength(1);
    expect(calls[0][0]).toBe("/api/auth/me");
  });

  it("with an expired stored token: refreshes first, then loads /me", async () => {
    localStorage.setItem("erp_agent_token", "expired");
    localStorage.setItem("erp_agent_token_expires_at", String(Date.now() - 60_000));

    mockFetchOnce(makeResponse({ access_token: "fresh", token_type: "bearer", expires_in_minutes: 15 }));
    mockFetchOnce(makeResponse(SAMPLE_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user?.id).toBe("u-1");
    expect(getToken()).toBe("fresh");

    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0]);
    expect(calls).toEqual(["/api/auth/refresh", "/api/auth/me"]);
  });

  it("with a stored token whose /me returns 401: refreshes, then retries /me", async () => {
    setToken("stale", 15);
    mockFetchOnce(makeResponse({ error: { code: 401, message: "Expired.", request_id: null } }, { status: 401 }));
    mockFetchOnce(makeResponse({ access_token: "fresh", token_type: "bearer", expires_in_minutes: 15 }));
    mockFetchOnce(makeResponse(SAMPLE_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user?.id).toBe("u-1");
    expect(getToken()).toBe("fresh");
  });

  it("with no stored token: attempts a refresh using the HttpOnly cookie", async () => {
    mockFetchOnce(makeResponse({ access_token: "fresh", token_type: "bearer", expires_in_minutes: 15 }));
    mockFetchOnce(makeResponse(SAMPLE_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user?.id).toBe("u-1");

    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0]);
    expect(calls).toEqual(["/api/auth/refresh", "/api/auth/me"]);
  });

  it("with no stored token and no session: stays logged out", async () => {
    mockFetchOnce(makeResponse({ error: { code: 401, message: "Session expired.", request_id: null } }, { status: 401 }));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
    expect(getToken()).toBeNull();
  });

  it("network failure during /me does NOT clear the stored token", async () => {
    setToken("kept", 15);
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new TypeError("network down"));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
    expect(getToken()).toBe("kept");
  });
});

// ---------------------------------------------------------------------------
// verifyOtp
// ---------------------------------------------------------------------------
describe("AuthProvider verifyOtp", () => {
  it("stores the new access token and loads the user", async () => {
    // Bootstrap: no session.
    mockFetchOnce(makeResponse({ error: { code: 401, message: "no session", request_id: null } }, { status: 401 }));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockFetchOnce(makeResponse({ access_token: "token-after-otp", token_type: "bearer", expires_in_minutes: 15 }));
    mockFetchOnce(makeResponse(SAMPLE_USER));

    await act(async () => {
      await result.current.verifyOtp("ref-abc", "123456");
    });

    expect(getToken()).toBe("token-after-otp");
    expect(result.current.user?.id).toBe("u-1");

    const urls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0]);
    expect(urls).toEqual([
      "/api/auth/refresh",
      "/api/auth/login/verify-otp",
      "/api/auth/me",
    ]);
  });

  it("propagates an error and does not leave a partially-set token on /me failure", async () => {
    mockFetchOnce(makeResponse({ error: { code: 401, message: "no session", request_id: null } }, { status: 401 }));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockFetchOnce(makeResponse({ access_token: "token-x", token_type: "bearer", expires_in_minutes: 15 }));
    mockFetchOnce(makeResponse({ error: { code: 401, message: "Expired.", request_id: null } }, { status: 401 }));

    await expect(
      act(async () => {
        await result.current.verifyOtp("ref-abc", "123456");
      }),
    ).rejects.toBeTruthy();

    expect(getToken()).toBeNull();
    expect(result.current.user).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// logout / logoutAll
// ---------------------------------------------------------------------------
describe("AuthProvider logout", () => {
  it("calls /api/auth/logout and clears local state", async () => {
    setToken("valid", 15);
    mockFetchOnce(makeResponse(SAMPLE_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockFetchOnce(makeResponse({ message: "Signed out." }));

    await act(async () => {
      await result.current.logout();
    });

    expect(getToken()).toBeNull();
    expect(result.current.user).toBeNull();

    const urls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0]);
    expect(urls).toContain("/api/auth/logout");
  });

  it("still clears local state when the backend call fails", async () => {
    setToken("valid", 15);
    mockFetchOnce(makeResponse(SAMPLE_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    (globalThis.fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new TypeError("network down"));

    await act(async () => {
      await result.current.logout();
    });

    expect(getToken()).toBeNull();
    expect(result.current.user).toBeNull();
  });
});

describe("AuthProvider logoutAll", () => {
  it("calls /api/auth/logout-all and clears local state", async () => {
    setToken("valid", 15);
    mockFetchOnce(makeResponse(SAMPLE_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockFetchOnce(makeResponse({ message: "Signed out of all devices." }));

    await act(async () => {
      await result.current.logoutAll();
    });

    expect(getToken()).toBeNull();
    expect(result.current.user).toBeNull();

    const urls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0]);
    expect(urls).toContain("/api/auth/logout-all");
  });
});

// ---------------------------------------------------------------------------
// Auth-expired signal
// ---------------------------------------------------------------------------
describe("AuthProvider subscription to onAuthExpired", () => {
  it("transitions to logged-out when a protected 401 fires", async () => {
    setToken("valid", 15);
    mockFetchOnce(makeResponse(SAMPLE_USER));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user?.id).toBe("u-1");

    // Simulate a 401 from a protected request elsewhere in the app.
    mockFetchOnce(makeResponse({ error: { code: 401, message: "Expired.", request_id: null } }, { status: 401 }));
    await act(async () => {
      try {
        const { api } = await import("../api/client");
        await api.me();
      } catch {
        // expected
      }
    });

    await waitFor(() => expect(result.current.user).toBeNull());
    expect(getToken()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Security invariant: JS never reads the refresh cookie
// ---------------------------------------------------------------------------
describe("refresh-token isolation", () => {
  it("does not read the refresh cookie from JavaScript", async () => {
    // A refresh cookie is only ever set by the backend as HttpOnly. In
    // jsdom, HttpOnly is not honoured, so simulate presence by setting
    // it in the cookie jar and confirming the frontend never uses it.
    document.cookie = "erp_refresh_token=should-not-be-used; path=/";
    const { readCsrfToken } = await import("../api/client");
    expect(readCsrfToken()).not.toBe("should-not-be-used");
    document.cookie = "erp_refresh_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  });
});