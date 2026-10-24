import type {
  AgentConfig,
  AgentTool,
  ApiKey,
  AuditPage,
  ChatResponse,
  Conversation,
  ConversationMessage,
  DemoConfig,
  Overview,
  Server,
  Tool,
  User,
} from "./types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const AGENT_BASE_URL = (import.meta.env.VITE_AGENT_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function readCookie(name: string): string | null {
  const match = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return requestWith(BASE_URL, path, init);
}

async function requestWith<T>(
  base: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = readCookie("urumi_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      // The session expired or was replaced (for example by a persona
      // switch). Let the app fall back to the entry screen instead of
      // displaying stale, role-sensitive data.
      window.dispatchEvent(new Event("urumi:unauthorized"));
    }
    throw new ApiError(
      response.status,
      payload.error ?? "error",
      payload.message ?? response.statusText,
    );
  }
  return payload as T;
}

export interface LoginResult {
  user: User;
  csrf_token: string;
}

export const api = {
  demo: () => request<DemoConfig>("/api/auth/demo"),
  demoSession: (persona: string) =>
    request<LoginResult>("/api/auth/demo/session", {
      method: "POST",
      body: JSON.stringify({ persona }),
    }),
  login: (email: string, password: string) =>
    request<LoginResult>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<{ message: string }>("/api/auth/logout", { method: "POST" }),
  me: () => request<User>("/api/auth/me"),

  overview: () => request<Overview>("/api/overview"),
  tools: () => request<Tool[]>("/api/tools"),

  servers: () => request<Server[]>("/api/servers"),
  createServer: (payload: {
    server_id: string;
    name: string;
    url: string;
    description?: string;
    health_url?: string;
    credential_type?: string;
    credential?: string;
    credential_header?: string;
  }) =>
    request<Server>("/api/servers", { method: "POST", body: JSON.stringify(payload) }),
  updateServer: (id: string, payload: Record<string, unknown>) =>
    request<Server>(`/api/servers/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteServer: (id: string) =>
    request<{ message: string }>(`/api/servers/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  setServerEnabled: (id: string, enabled: boolean) =>
    request<Server>(`/api/servers/${encodeURIComponent(id)}/enable?enabled=${enabled}`, {
      method: "POST",
    }),
  refreshServer: (id: string) =>
    request<Server>(`/api/servers/${encodeURIComponent(id)}/refresh`, { method: "POST" }),

  keys: () => request<ApiKey[]>("/api/keys"),
  createKey: (name: string, userId?: number) =>
    request<ApiKey & { api_key: string }>("/api/keys", {
      method: "POST",
      body: JSON.stringify({ name, user_id: userId }),
    }),
  deleteKey: (id: number) =>
    request<{ message: string }>(`/api/keys/${id}`, { method: "DELETE" }),

  audit: (params: { page?: number; per_page?: number; status?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.page) query.set("page", String(params.page));
    if (params.per_page) query.set("per_page", String(params.per_page));
    if (params.status) query.set("status", params.status);
    const suffix = query.toString();
    return request<AuditPage>(`/api/audit${suffix ? `?${suffix}` : ""}`);
  },

  users: () => request<User[]>("/api/users"),
  createUser: (payload: {
    email: string;
    password: string;
    display_name?: string;
    roles: string[];
  }) => request<User>("/api/users", { method: "POST", body: JSON.stringify(payload) }),
  updateUser: (id: number, payload: Record<string, unknown>) =>
    request<User>(`/api/users/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  setUserPassword: (id: number, password: string) =>
    request<User>(`/api/users/${id}/password`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
};

export const agentApi = {
  config: () => requestWith<AgentConfig>(AGENT_BASE_URL, "/agent/api/config"),
  tools: () => requestWith<AgentTool[]>(AGENT_BASE_URL, "/agent/api/tools"),
  chat: (message: string, conversationId?: number) =>
    requestWith<ChatResponse>(AGENT_BASE_URL, "/agent/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, conversation_id: conversationId ?? null }),
    }),
  conversations: () =>
    requestWith<Conversation[]>(AGENT_BASE_URL, "/agent/api/conversations"),
  conversation: (id: number) =>
    requestWith<{ conversation: Conversation; messages: ConversationMessage[] }>(
      AGENT_BASE_URL,
      `/agent/api/conversations/${id}`,
    ),
  deleteConversation: (id: number) =>
    requestWith<{ message: string }>(AGENT_BASE_URL, `/agent/api/conversations/${id}`, {
      method: "DELETE",
    }),
};
