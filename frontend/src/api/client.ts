import type {
  ChatStreamEvent,
  DocumentRef,
  NextAction,
  ProjectStatus,
  ProjectSummary,
  RequirementItem,
  ProcessStep,
  SolutionDecision,
  TestCase,
  TrainingStep,
  ProjectIssue,
  ProjectHealth,
  CoverageGaps,
  UploadedDocument,
  ReviewAction,
  User,
  SignupPayload,
  MessageResponse,
  PendingLoginResponse,
} from "../types";
import { parseSseChunk } from "./sse";

const TOKEN_KEY = "erp_agent_token";
const TOKEN_EXPIRES_KEY = "erp_agent_token_expires_at";

// ---------------------------------------------------------------------------
// CSRF
// ---------------------------------------------------------------------------
// The backend issues a JS-readable CSRF cookie alongside the HttpOnly
// refresh cookie (both set by POST /api/auth/login/verify-otp and by
// every successful POST /api/auth/refresh). The SPA echoes the cookie
// value in a header on cookie-authenticated requests — refresh and, when
// a session is present, logout.
//
// CRITICAL: the backend rotates the CSRF cookie on every successful
// refresh (Step 6/7 design). The client must re-read the cookie AFTER
// every refresh — caching the value in memory across a refresh will
// fail the next state-changing request. The helpers below always read
// from document.cookie; nothing in this file caches the CSRF value.
//
// The refresh cookie itself is HttpOnly and is never read from JS. The
// names here mirror the backend defaults in
// src/config/settings.py (auth_csrf_cookie_name / auth_csrf_header_name).
// If those defaults change, this constant must be updated to match.
export const CSRF_COOKIE_NAME = "erp_csrf_token";
export const CSRF_HEADER_NAME = "X-CSRF-Token";

export function readCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const name = CSRF_COOKIE_NAME.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = document.cookie.match(
    new RegExp("(?:^|;\\s*)" + name + "=([^;]*)"),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------
export type ApiErrorKind =
  | "auth"
  | "validation"
  | "rate_limit"
  | "not_found"
  | "conflict"
  | "server"
  | "network"
  | "aborted"
  | "unknown";

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  readonly requestId: string | null;
  readonly developerMessage: string;
  readonly retryAfterSeconds: number | null;
  readonly details: unknown;

  constructor(args: {
    status: number;
    kind: ApiErrorKind;
    message: string;
    developerMessage?: string;
    requestId?: string | null;
    retryAfterSeconds?: number | null;
    details?: unknown;
  }) {
    super(args.message);
    this.name = "ApiError";
    this.status = args.status;
    this.kind = args.kind;
    this.requestId = args.requestId ?? null;
    this.developerMessage = args.developerMessage ?? args.message;
    this.retryAfterSeconds = args.retryAfterSeconds ?? null;
    this.details = args.details;
  }

  get isAuthError(): boolean { return this.kind === "auth"; }
  get isRateLimit(): boolean { return this.kind === "rate_limit"; }
  get isNetworkError(): boolean { return this.kind === "network"; }
  get isAbort(): boolean { return this.kind === "aborted"; }
}

// ---------------------------------------------------------------------------
// Token storage
// ---------------------------------------------------------------------------
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string, expiresInMinutes?: number): void {
  localStorage.setItem(TOKEN_KEY, token);
  if (typeof expiresInMinutes === "number" && expiresInMinutes > 0) {
    const expiresAt = Date.now() + expiresInMinutes * 60 * 1000;
    localStorage.setItem(TOKEN_EXPIRES_KEY, String(expiresAt));
  } else {
    localStorage.removeItem(TOKEN_EXPIRES_KEY);
  }
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TOKEN_EXPIRES_KEY);
}

export function isTokenExpired(): boolean {
  const raw = localStorage.getItem(TOKEN_EXPIRES_KEY);
  if (!raw) return false;
  const expiresAt = Number(raw);
  if (!Number.isFinite(expiresAt)) return false;
  return Date.now() >= expiresAt - 5_000;
}

// ---------------------------------------------------------------------------
// Auth-expired signal
// ---------------------------------------------------------------------------
type AuthExpiredHandler = () => void;
const authExpiredHandlers = new Set<AuthExpiredHandler>();

export function onAuthExpired(handler: AuthExpiredHandler): () => void {
  authExpiredHandlers.add(handler);
  return () => {
    authExpiredHandlers.delete(handler);
  };
}

function fireAuthExpired(): void {
  clearToken();
  for (const handler of authExpiredHandlers) {
    try {
      handler();
    } catch {
      // A misbehaving subscriber must not prevent the others from running.
    }
  }
}

// Endpoints that legitimately return 400/401/403 as part of their
// public, unauthenticated contract. A failure from any of these must
// NOT trigger the app-wide logout. Every other 401 means the access
// token is bad and the app should transition to logged-out.
//
// - /login, /login/verify-otp, /login/resend-otp: bad credentials or OTP
// - /signup, /verify-email, /resend-verification: enumeration-resistant
// - /password-reset/*: enumeration-resistant
// - /refresh: 401 when no session, 403 on CSRF mismatch — both normal
const PUBLIC_AUTH_ENDPOINTS = new Set<string>([
  "/api/auth/signup",
  "/api/auth/login",
  "/api/auth/verify-email",
  "/api/auth/resend-verification",
  "/api/auth/login/verify-otp",
  "/api/auth/login/resend-otp",
  "/api/auth/password-reset/request",
  "/api/auth/password-reset/complete",
  "/api/auth/refresh",
]);

function isPublicAuthEndpoint(path: string): boolean {
  return PUBLIC_AUTH_ENDPOINTS.has(path);
}

// ---------------------------------------------------------------------------
// Error normalization
// ---------------------------------------------------------------------------
function classifyStatus(status: number): ApiErrorKind {
  if (status === 401 || status === 403) return "auth";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 400 || status === 413 || status === 422) return "validation";
  if (status === 429) return "rate_limit";
  if (status >= 500) return "server";
  return "unknown";
}

function parseRetryAfter(headers: Headers): number | null {
  const raw = headers.get("Retry-After");
  if (!raw) return null;
  const seconds = Number(raw);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.round(seconds);
  const asDate = Date.parse(raw);
  if (Number.isFinite(asDate)) {
    return Math.max(0, Math.round((asDate - Date.now()) / 1000));
  }
  return null;
}

function isAbortError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === "AbortError") return true;
  if (err instanceof Error && err.name === "AbortError") return true;
  return false;
}

function normalizeErrorResponse(
  status: number,
  headers: Headers,
  body: unknown,
): ApiError {
  const kind = classifyStatus(status);
  const headerRequestId = headers.get("X-Request-ID");
  const retryAfterSeconds = kind === "rate_limit" ? parseRetryAfter(headers) : null;

  let userMessage: string | null = null;
  let developerMessage = "";
  let details: unknown;
  let envelopeRequestId: string | null = null;

  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;

    if ("error" in b) {
      const err = b.error;
      if (err && typeof err === "object") {
        const e = err as Record<string, unknown>;
        if (typeof e.message === "string" && e.message) {
          userMessage = e.message;
          developerMessage = e.message;
        }
        if (typeof e.request_id === "string" && e.request_id) {
          envelopeRequestId = e.request_id;
        }
      } else if (typeof err === "string" && err) {
        userMessage = err;
        developerMessage = err;
      }
    }

    if (!userMessage && "detail" in b) {
      const detail = b.detail;
      if (typeof detail === "string") {
        userMessage = detail;
        developerMessage = detail;
      } else if (Array.isArray(detail)) {
        const parts: string[] = [];
        for (const item of detail) {
          if (item && typeof item === "object") {
            const i = item as Record<string, unknown>;
            const loc = Array.isArray(i.loc) ? i.loc.join(".") : "";
            const msg = typeof i.msg === "string" ? i.msg : "";
            if (msg) parts.push(loc ? `${loc}: ${msg}` : msg);
          }
        }
        if (parts.length) {
          userMessage = parts.join("; ");
          developerMessage = userMessage;
          details = detail;
        }
      }
    }
  }

  if (!userMessage) {
    switch (kind) {
      case "auth":
        userMessage =
          status === 403
            ? "You don't have access to this."
            : "Your session has expired. Please sign in again.";
        break;
      case "validation":
        userMessage =
          "That request couldn't be processed. Please check your input and try again.";
        break;
      case "rate_limit":
        userMessage = retryAfterSeconds
          ? `Too many requests. Please wait ${retryAfterSeconds}s and try again.`
          : "Too many requests. Please wait a moment and try again.";
        break;
      case "not_found":
        userMessage = "That item no longer exists.";
        break;
      case "conflict":
        userMessage = "That action conflicts with the current state.";
        break;
      case "server":
        userMessage = "The server had a problem. Please try again shortly.";
        break;
      default:
        userMessage = `Request failed (${status}).`;
    }
    developerMessage = developerMessage || userMessage;
  }

  return new ApiError({
    status,
    kind,
    message: userMessage,
    developerMessage,
    requestId: envelopeRequestId ?? headerRequestId,
    retryAfterSeconds,
    details,
  });
}

// ---------------------------------------------------------------------------
// Request helper
// ---------------------------------------------------------------------------
async function parseResponseBody(res: Response): Promise<unknown> {
  if (res.status === 204 || res.status === 205) return undefined;
  const text = await res.text();
  if (!text) return undefined;
  const contentType = res.headers.get("Content-Type") ?? "";
  const looksJson =
    contentType.includes("application/json") ||
    text.startsWith("{") ||
    text.startsWith("[");
  if (!looksJson) return text;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (typeof options.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token && !isPublicAuthEndpoint(path)) {
  headers.set("Authorization", `Bearer ${token}`);
  }

  let res: Response;
  try {
    // credentials: "include" is required so the browser sends and
    // stores the refresh and CSRF cookies on auth endpoints. It is
    // harmless on endpoints that do not use cookies.
    res = await fetch(path, {
      ...options,
      headers,
      credentials: "include",
    });
  } catch (err) {
    if (isAbortError(err)) {
      throw new ApiError({
        status: 0,
        kind: "aborted",
        message: "Request cancelled.",
        developerMessage: "Request aborted by caller.",
      });
    }
    throw new ApiError({
      status: 0,
      kind: "network",
      message: "Couldn't reach the server. Check your connection and try again.",
      developerMessage: err instanceof Error ? err.message : String(err),
    });
  }

  const body = await parseResponseBody(res);

  if (!res.ok) {
    const apiError = normalizeErrorResponse(res.status, res.headers, body);
    if (res.status === 401 && !isPublicAuthEndpoint(path)) {
      fireAuthExpired();
    }
    throw apiError;
  }

  return body as T;
}

// ---------------------------------------------------------------------------
// Types for specific responses
// ---------------------------------------------------------------------------
type StartProjectResponse = {
  session_id: string;
  project_name: string;
  next_action?: NextAction | null;
};

type TokenResponse = {
  access_token: string;
  expires_in_minutes: number;
};

type MessageRecord = { role: string; content: string; timestamp: string };

// ---------------------------------------------------------------------------
// Download helper
// ---------------------------------------------------------------------------
function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

// ---------------------------------------------------------------------------
// API surface
// ---------------------------------------------------------------------------
export const api = {
  // --- Auth: unauthenticated flow endpoints ---

  /**
   * Create an account. The response is enumeration-resistant: identical
   * whether the email was new or already registered. NO tokens are
   * issued; the user must verify their email and then sign in with the
   * password + OTP flow.
   */
  async signup(payload: SignupPayload): Promise<MessageResponse> {
    return request<MessageResponse>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * Consume an email-verification token. The token is presented by the
   * user from the emailed link. Invalid/expired tokens return the same
   * generic 400 (enumeration-resistant).
   */
  async verifyEmail(token: string): Promise<MessageResponse> {
    return request<MessageResponse>("/api/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  },

  /**
   * Request a new verification email. Enumeration-resistant: identical
   * response whether the email is unknown, already verified, or newly
   * sent.
   */
  async resendVerification(email: string): Promise<MessageResponse> {
    return request<MessageResponse>("/api/auth/resend-verification", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },

  /**
   * Stage 1 of login: verify email + password.
   *
   * The response contains ONLY an opaque `pending_auth_ref`. It is NOT
   * an access token, NOT a refresh token, and NOT a bearer credential
   * for any authenticated endpoint. Store it only for the MFA step and
   * discard it once the OTP is verified (or the flow is abandoned).
   */
  async initiateLogin(
    email: string,
    password: string,
  ): Promise<PendingLoginResponse> {
    return request<PendingLoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  /**
   * Stage 2 of login: verify the OTP.
   *
   * On success, the backend sets the HttpOnly refresh cookie and a
   * JS-readable CSRF cookie, and returns the access token in the body.
   * The refresh token is never visible to JS.
   */
  async verifyOtp(
    pendingAuthRef: string,
    code: string,
  ): Promise<TokenResponse> {
    return request<TokenResponse>("/api/auth/login/verify-otp", {
      method: "POST",
      body: JSON.stringify({ pending_auth_ref: pendingAuthRef, code }),
    });
  },

  /**
   * Request a new OTP for an existing pending-auth flow. Enumeration-
   * resistant: an unknown ref and a valid ref produce the same shape.
   */
  async resendOtp(pendingAuthRef: string): Promise<PendingLoginResponse> {
    return request<PendingLoginResponse>("/api/auth/login/resend-otp", {
      method: "POST",
      body: JSON.stringify({ pending_auth_ref: pendingAuthRef }),
    });
  },

  /**
   * Rotate the refresh token and issue a new access token.
   *
   * The refresh token is read exclusively from the HttpOnly cookie by
   * the backend. The CSRF value is read fresh from document.cookie on
   * every call — the backend rotates the CSRF cookie on every
   * successful refresh, so a cached value would fail the next request.
   *
   * On any failure (no session, expired, revoked, reused, CSRF
   * mismatch) the backend clears the session cookies and returns a
   * generic 401/403. The caller treats any error as "session not
   * available" and clears local token state.
   */
  async refresh(): Promise<TokenResponse> {
    const csrf = readCsrfToken();
    const headers: HeadersInit = {};
    if (csrf) headers[CSRF_HEADER_NAME] = csrf;
    return request<TokenResponse>("/api/auth/refresh", {
      method: "POST",
      headers,
    });
  },

  /**
   * Revoke the current refresh session server-side and clear the
   * session cookies. Idempotent: succeeds whether or not a session
   * cookie is present. The CSRF header is included whenever the CSRF
   * cookie is present — the backend requires it when a refresh cookie
   * exists.
   */
  async logout(): Promise<MessageResponse> {
    const csrf = readCsrfToken();
    const headers: HeadersInit = {};
    if (csrf) headers[CSRF_HEADER_NAME] = csrf;
    return request<MessageResponse>("/api/auth/logout", {
      method: "POST",
      headers,
    });
  },

  /**
   * Revoke every active refresh session for the authenticated user.
   * Requires a Bearer access token. The backend clears the current
   * session cookies as part of the response; existing access JWTs
   * remain valid until their short expiry.
   */
  async logoutAll(): Promise<MessageResponse> {
    return request<MessageResponse>("/api/auth/logout-all", {
      method: "POST",
    });
  },

  /**
   * Request a password-reset email. Enumeration-resistant: identical
   * response whether the email exists or not. The token is never
   * returned through the API.
   */
  async requestPasswordReset(email: string): Promise<MessageResponse> {
    return request<MessageResponse>("/api/auth/password-reset/request", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },

  /**
   * Complete a password reset with the token from the reset email.
   * The token is presented by the user; invalid/expired tokens return
   * the same generic 400.
   */
  async completePasswordReset(
    token: string,
    newPassword: string,
  ): Promise<MessageResponse> {
    return request<MessageResponse>("/api/auth/password-reset/complete", {
      method: "POST",
      body: JSON.stringify({ token, new_password: newPassword }),
    });
  },

  // --- Auth: authenticated endpoints ---

  async me() {
    return request<User>("/api/auth/me");
  },

  async updateAccountSettings(name: string) {
    return request<User>("/api/auth/settings", {
      method: "PATCH",
      body: JSON.stringify({ name: name || null }),
    });
  },

  async uploadProfilePicture(file: File) {
    const token = getToken();
    const form = new FormData();
    form.append("file", file);
    let response: Response;
    try {
      response = await fetch("/api/auth/profile-picture", {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
        credentials: "include",
      });
    } catch (err) {
      if (isAbortError(err)) {
        throw new ApiError({
          status: 0,
          kind: "aborted",
          message: "Upload cancelled.",
        });
      }
      throw new ApiError({
        status: 0,
        kind: "network",
        message: "Couldn't reach the server. Check your connection and try again.",
        developerMessage: err instanceof Error ? err.message : String(err),
      });
    }
    const body = await parseResponseBody(response);
    if (!response.ok) {
      const apiError = normalizeErrorResponse(response.status, response.headers, body);
      if (response.status === 401) fireAuthExpired();
      throw apiError;
    }
    return body as User;
  },

  async changePassword(current_password: string, new_password: string) {
    return request<{ success: boolean }>("/api/auth/password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    });
  },

  async deleteAccount() {
    return request<{ deleted: boolean }>("/api/auth/account", { method: "DELETE" });
  },

  // --- Projects ---

  async listProjects(includeArchived = false) {
    return request<{ projects: ProjectSummary[] }>(
      `/api/projects?include_archived=${includeArchived}`,
    );
  },

  async startProject(project_name: string, module: string, erp_system?: string) {
    return request<StartProjectResponse>("/api/projects/start", {
      method: "POST",
      body: JSON.stringify({ project_name, module, erp_system }),
    });
  },

  async renameProject(sessionId: string, project_name: string) {
    return request<{ session_id: string; project_name: string }>(
      `/api/projects/${sessionId}`,
      { method: "PATCH", body: JSON.stringify({ project_name }) },
    );
  },

  async archiveProject(sessionId: string) {
    return request<{ session_id: string; archived: boolean }>(
      `/api/projects/${sessionId}`,
      { method: "DELETE" },
    );
  },

  async deleteProject(sessionId: string) {
    return request<{ session_id: string; deleted: boolean }>(
      `/api/projects/${sessionId}/permanent`,
      { method: "DELETE" },
    );
  },

  async getMessages(sessionId: string, signal?: AbortSignal) {
    return request<{ session_id: string; messages: MessageRecord[] }>(
      `/api/projects/${sessionId}/messages`,
      { signal },
    );
  },

  async projectStatus(sessionId: string) {
    return request<ProjectStatus>(`/api/projects/${sessionId}/status`);
  },

  async listDocuments(sessionId: string) {
    return request<{ session_id: string; documents: DocumentRef[] }>(
      `/api/projects/${sessionId}/documents`,
    );
  },

  async downloadDocument(sessionId: string, filename: string) {
    const token = getToken();
    let res: Response;
    try {
      res = await fetch(
        `/api/projects/${sessionId}/documents/${encodeURIComponent(filename)}`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          credentials: "include",
        },
      );
    } catch (err) {
      if (isAbortError(err)) {
        throw new ApiError({ status: 0, kind: "aborted", message: "Download cancelled." });
      }
      throw new ApiError({
        status: 0,
        kind: "network",
        message: "Couldn't reach the server. Check your connection and try again.",
      });
    }
    if (!res.ok) {
      const body = await parseResponseBody(res);
      const apiError = normalizeErrorResponse(res.status, res.headers, body);
      if (res.status === 401) fireAuthExpired();
      throw apiError;
    }
    triggerBlobDownload(await res.blob(), filename);
  },

  async generateProjectReport(sessionId: string) {
    return request<{ session_id: string; filename: string }>(
      `/api/projects/${sessionId}/report`,
      { method: "POST" },
    );
  },

  async submitFeedback(sessionId: string | null, rating: number | null, comment: string) {
    return request<{ success: boolean }>("/api/feedback", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, rating, comment }),
    });
  },

  // --- Project intelligence ---

  async getRequirements(sessionId: string) {
    return request<{ session_id: string; requirements: RequirementItem[] }>(
      `/api/projects/${sessionId}/requirements`,
    );
  },

  async getProcessSteps(sessionId: string) {
    return request<{ session_id: string; process_steps: ProcessStep[] }>(
      `/api/projects/${sessionId}/process-steps`,
    );
  },

  async getSolutionDecisions(sessionId: string) {
    return request<{ session_id: string; solution_decisions: SolutionDecision[] }>(
      `/api/projects/${sessionId}/solution-decisions`,
    );
  },

  async getTestCases(sessionId: string) {
    return request<{ session_id: string; test_cases: TestCase[] }>(
      `/api/projects/${sessionId}/test-cases`,
    );
  },

  async getTrainingSteps(sessionId: string) {
    return request<{ session_id: string; training_steps: TrainingStep[] }>(
      `/api/projects/${sessionId}/training-steps`,
    );
  },

  async getIssues(sessionId: string, status?: string | null) {
    const url = status
      ? `/api/projects/${sessionId}/issues?status=${encodeURIComponent(status)}`
      : `/api/projects/${sessionId}/issues`;
    return request<{ session_id: string; issues: ProjectIssue[] }>(url);
  },

  async getProjectHealth(sessionId: string) {
    return request<ProjectHealth>(`/api/projects/${sessionId}/health`);
  },

  async getCoverageGaps(sessionId: string) {
    return request<CoverageGaps>(`/api/projects/${sessionId}/coverage-gaps`);
  },

  async submitReviewAction(
    sessionId: string,
    objectType: string,
    objectId: string,
    action: ReviewAction,
    note?: string,
  ) {
    return request<{ action_id: string; success: boolean }>(`/api/projects/${sessionId}/review`, {
      method: "POST",
      body: JSON.stringify({ object_type: objectType, object_id: objectId, action, note }),
    });
  },

  async runConsistencyCheck(sessionId: string) {
    return request<{ session_id: string; findings_count: number; findings: unknown[] }>(
      `/api/projects/${sessionId}/consistency-check`,
      { method: "POST" },
    );
  },

  // --- Uploaded project documents ---

  async listUploads(sessionId: string) {
    return request<{ session_id: string; documents: UploadedDocument[] }>(
      `/api/projects/${sessionId}/uploads`,
    );
  },

  async uploadDocument(sessionId: string, file: File) {
    const token = getToken();
    const form = new FormData();
    form.append("file", file);
    let res: Response;
    try {
      res = await fetch(`/api/projects/${sessionId}/uploads`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
        credentials: "include",
      });
    } catch (err) {
      if (isAbortError(err)) {
        throw new ApiError({ status: 0, kind: "aborted", message: "Upload cancelled." });
      }
      throw new ApiError({
        status: 0,
        kind: "network",
        message: "Couldn't reach the server. Check your connection and try again.",
      });
    }
    const body = await parseResponseBody(res);
    if (!res.ok) {
      const apiError = normalizeErrorResponse(res.status, res.headers, body);
      if (res.status === 401) fireAuthExpired();
      throw apiError;
    }
    return body as {
      id: string;
      filename: string;
      size_bytes: number;
      extracted_text_chars: number;
    };
  },

  async downloadUpload(sessionId: string, documentId: string, filename: string) {
    const token = getToken();
    let res: Response;
    try {
      res = await fetch(
        `/api/projects/${sessionId}/uploads/${encodeURIComponent(documentId)}/download`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          credentials: "include",
        },
      );
    } catch (err) {
      if (isAbortError(err)) {
        throw new ApiError({ status: 0, kind: "aborted", message: "Download cancelled." });
      }
      throw new ApiError({
        status: 0,
        kind: "network",
        message: "Couldn't reach the server. Check your connection and try again.",
      });
    }
    if (!res.ok) {
      const body = await parseResponseBody(res);
      const apiError = normalizeErrorResponse(res.status, res.headers, body);
      if (res.status === 401) fireAuthExpired();
      throw apiError;
    }
    triggerBlobDownload(await res.blob(), filename);
  },

  async deleteUpload(sessionId: string, documentId: string) {
    return request<{ id: string; deleted: boolean }>(
      `/api/projects/${sessionId}/uploads/${documentId}`,
      { method: "DELETE" },
    );
  },

  // --- Chat SSE ---

  async streamChat(
    message: string,
    sessionId: string | null,
    onEvent: (event: ChatStreamEvent) => void,
    signal?: AbortSignal,
    agentHint?: string,
    preferWeb?: boolean,
  ): Promise<void> {
    const token = getToken();

    let res: Response;
    try {
      res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message,
          session_id: sessionId,
          agent_hint: agentHint,
          prefer_web: preferWeb ?? false,
        }),
        signal,
        credentials: "include",
      });
    } catch (err) {
      if (isAbortError(err)) {
        throw new ApiError({
          status: 0,
          kind: "aborted",
          message: "Request cancelled.",
        });
      }
      throw new ApiError({
        status: 0,
        kind: "network",
        message: "Couldn't reach the server. Check your connection and try again.",
        developerMessage: err instanceof Error ? err.message : String(err),
      });
    }

    if (!res.ok || !res.body) {
      const body = await parseResponseBody(res);
      const apiError = normalizeErrorResponse(res.status, res.headers, body);
      if (res.status === 401) fireAuthExpired();
      throw apiError;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { events, remainder } = parseSseChunk(buffer);
        buffer = remainder;
        for (const event of events) onEvent(event);
      }

      if (buffer.trim()) {
        const { events } = parseSseChunk(buffer + "\n\n");
        for (const event of events) onEvent(event);
      }
    } catch (err) {
      if (isAbortError(err)) {
        throw new ApiError({
          status: 0,
          kind: "aborted",
          message: "Request cancelled.",
        });
      }
      throw new ApiError({
        status: 0,
        kind: "network",
        message: "The connection was interrupted. Please try again.",
        developerMessage: err instanceof Error ? err.message : String(err),
      });
    }
  },
};