import type {
  ApiErrorBody,
  ChatStreamEvent,
  DocumentRef,
  NextAction,
  ProjectStatus,
  ProjectSummary,
  User,
} from "../types";
import { parseSseChunk } from "./sse";

const TOKEN_KEY = "erp_agent_token";

type StartProjectResponse = {
  session_id: string;
  project_name: string;
  next_action?: NextAction | null;
};

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  requestId: string | null;

  constructor(status: number, message: string, requestId: string | null) {
    super(message);
    this.status = status;
    this.requestId = requestId;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(path, { ...options, headers });

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    let requestId: string | null = res.headers.get("X-Request-ID");
    try {
      const body = (await res.json()) as ApiErrorBody;
      if (body?.error?.message) message = body.error.message;
      if (body?.error?.request_id) requestId = body.error.request_id;
    } catch {
      // Body wasn't JSON (or was empty) - the generic message stands.
    }
    if (res.status === 401) clearToken();
    throw new ApiError(res.status, message, requestId);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  async signup(email: string, password: string) {
    return request<{ access_token: string }>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  async login(email: string, password: string) {
    return request<{ access_token: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  async me() {
    return request<User>("/api/auth/me");
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

  async getMessages(sessionId: string) {
    return request<{ session_id: string; messages: { role: string; content: string; timestamp: string }[] }>(
      `/api/projects/${sessionId}/messages`,
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
    const res = await fetch(`/api/projects/${sessionId}/documents/${filename}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new ApiError(res.status, "Could not download document", null);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  async submitFeedback(sessionId: string | null, rating: number | null, comment: string) {
    return request<{ success: boolean }>("/api/feedback", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, rating, comment }),
    });
  },

  /**
   * Streams a chat turn via SSE, invoking onEvent for each parsed event as
   * it arrives. Uses `fetch` + a manual reader (not `EventSource`) because
   * this needs to be a POST with an Authorization header and a JSON body -
   * EventSource only supports GET with no custom headers.
   */
  async streamChat(
    message: string,
    sessionId: string | null,
    onEvent: (event: ChatStreamEvent) => void,
    signal?: AbortSignal,
    agentHint?: string,
  ): Promise<void> {
    const token = getToken();
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message, session_id: sessionId, agent_hint: agentHint }),
      signal,
    });

    if (!res.ok || !res.body) {
      let msg = `Request failed (${res.status})`;
      try {
        const body = (await res.json()) as ApiErrorBody;
        if (body?.error?.message) msg = body.error.message;
      } catch {
        /* generic message stands */
      }
      if (res.status === 401) clearToken();
      throw new ApiError(res.status, msg, res.headers.get("X-Request-ID"));
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, remainder } = parseSseChunk(buffer);
      buffer = remainder;
      for (const event of events) onEvent(event);
    }
  },
};
