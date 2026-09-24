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
} from "../types";
import { parseSseChunk } from "./sse";

const TOKEN_KEY = "erp_agent_token";
const TOKEN_EXPIRES_KEY = "erp_agent_token_expires_at";

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/**
 * Discriminator for the kind of failure an ApiError represents. Callers
 * should branch on `kind`, not on `status` or on the presence/absence of
 * a message string - the message is user-facing and may change.
 */
export type ApiErrorKind =
  | "auth"        // 401 (session expired / invalid) or 403 (forbidden)
  | "validation"  // 400, 413, 422 - the caller sent something wrong
  | "rate_limit"  // 429
  | "not_found"   // 404
  | "conflict"    // 409 - state disagreement (already archived, etc.)
  | "server"      // 5xx
  | "network"     // fetch itself failed
  | "aborted"     // caller cancelled via AbortController
  | "unknown";    // anything else

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
// Two keys instead of one: the original `erp_agent_token` key is preserved
// so existing sessions survive the upgrade, and a companion key records
// when the token expires. The companion key is absent when the server did
// not return an expiry - `isTokenExpired()` treats "unknown" as "not
// expired" rather than guessing.

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

/**
 * True when we know the token has expired (or is within a small safety
 * margin of expiring). Returns false when the expiry is unknown, so a
 * token obtained before this code shipped is not spuriously rejected.
 */
export function isTokenExpired(): boolean {
  const raw = localStorage.getItem(TOKEN_EXPIRES_KEY);
  if (!raw) return false;
  const expiresAt = Number(raw);
  if (!Number.isFinite(expiresAt)) return false;
  // 5s margin: avoids handing a token to the server that will expire in
  // flight and produce a confusing mid-request 401.
  return Date.now() >= expiresAt - 5_000;
}

// ---------------------------------------------------------------------------
// Auth-expired signal
// ---------------------------------------------------------------------------
// The client owns the token; AuthContext owns the user object. When any
// protected request returns 401, the client fires this signal and the
// AuthContext subscriber transitions the app to the logged-out state.
// The subscriber pattern (rather than an import of AuthContext here)
// keeps client.ts free of React and prevents a circular import.

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

function isAuthEndpoint(path: string): boolean {
  // A 401 from these endpoints is a credentials failure, not an expired
  // session, so it must not trigger the global logout.
  return path === "/api/auth/login" || path === "/api/auth/signup";
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

/**
 * Turn an HTTP response (status, headers, parsed or unparsed body) into a
 * uniform ApiError. The three error shapes the backend can emit are all
 * handled here:
 *
 *   A. HTTPException / unhandled 500 -> { error: { code, message, request_id } }
 *   B. SlowAPI rate limit           -> { error: "Rate limit exceeded: ..." }
 *   C. FastAPI validation (422)     -> { detail: [ { loc, msg, type }, ... ] }
 */
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

    // Shape A: { error: { code, message, request_id } }
    // Shape B: { error: "string" }
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

    // Shape C: { detail: "..." } or { detail: [ { loc, msg, type }, ... ] }
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
    // Kind-specific fallback so the user never sees "Request failed (500)".
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
    // Server declared JSON but sent something else - return the raw
    // text rather than throwing, so callers still get a usable payload.
    return text;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  // Only declare a JSON body when there is a string body. GET with
  // Content-Type: application/json and no body is valid but triggers
  // unnecessary CORS preflights and looks like a bug to reviewers.
  if (typeof options.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(path, { ...options, headers });
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
    if (res.status === 401 && !isAuthEndpoint(path)) {
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

/**
 * Trigger a browser download from a Blob. The object URL is revoked on a
 * short delay rather than synchronously: some browsers cancel the
 * download if the URL is revoked before the fetch has actually started,
 * which manifests as "the file just doesn't download sometimes".
 */
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
  async signup(payload: SignupPayload): Promise<TokenResponse> {
    return request<TokenResponse>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async login(email: string, password: string): Promise<TokenResponse> {
    return request<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

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
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
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

  /**
   * List issues for a project. Pass a specific status to filter; pass
   * `null` / `undefined` to omit the query parameter entirely, in which
   * case the backend applies its own default ("open"). Note: the backend
   * endpoint does not currently support "all statuses" - that is a
   * backend limitation, not a client one.
   */
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
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
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

  /**
   * Streams a chat turn via SSE, invoking onEvent for each parsed event
   * as it arrives. Uses fetch + a manual reader (not EventSource) because
   * this is a POST with an Authorization header and a JSON body -
   * EventSource only supports GET with no custom headers.
   *
   * The trailing buffer is flushed after the stream closes, so an event
   * whose `\n\n` terminator never arrived (because the connection ended
   * immediately after the last chunk) is still dispatched.
   */
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

      // Flush any event whose terminating blank line never arrived.
      // `parseSseChunk` needs a separator, so we append one.
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