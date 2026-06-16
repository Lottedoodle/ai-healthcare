import type {
  ChatSession,
  SendMessageResponse,
  SessionDetail,
  UserProfile,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  token: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(options.headers ?? {}),
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, String(detail));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  me: (token: string) => request<UserProfile>("/api/me", token),

  listSessions: (token: string) =>
    request<ChatSession[]>("/api/sessions", token),

  createSession: (token: string, title = "New chat") =>
    request<ChatSession>("/api/sessions", token, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),

  getSession: (token: string, sessionId: string) =>
    request<SessionDetail>(`/api/sessions/${sessionId}`, token),

  deleteSession: (token: string, sessionId: string) =>
    request<void>(`/api/sessions/${sessionId}`, token, { method: "DELETE" }),

  sendMessage: (token: string, sessionId: string, content: string) =>
    request<SendMessageResponse>(`/api/sessions/${sessionId}/messages`, token, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
};

export { ApiError };
