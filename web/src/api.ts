import type {
  AgentResponse,
  ExportItem,
  Me,
  MemoryItem,
  MetricDef,
  Session,
  SessionDetail,
} from "./types";

export type AlertItem = {
  id: string;
  shop_id: string;
  severity: string;
  rule: string;
  message: string;
  metric_code: string;
  value: number;
  status: string;
  created_at: string;
};

const TOKEN_KEY = "emmerce_token";
const ACCOUNT_KEY = "emmerce_account";

function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export async function login(account = "owner") {
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account }),
  });
  if (!res.ok) {
    throw new Error((await res.text()) || res.statusText);
  }
  const body = (await res.json()) as { token: string } & Me;
  sessionStorage.setItem(TOKEN_KEY, body.token);
  sessionStorage.setItem(ACCOUNT_KEY, account);
  return body;
}

async function authHeaders(): Promise<HeadersInit> {
  if (!getToken()) {
    await login(sessionStorage.getItem(ACCOUNT_KEY) || "owner");
  }
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${getToken()}`,
  };
}

async function request<T>(path: string, init?: RequestInit, retry = true): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(await authHeaders()),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401 && retry) {
    await login(sessionStorage.getItem(ACCOUNT_KEY) || "owner");
    return request<T>(path, init, false);
  }
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  login,
  me: () => request<Me>("/api/v1/me"),
  listSessions: async () => {
    const page = await request<{ items: Session[]; total: number }>("/api/v1/sessions");
    return page.items;
  },
  createSession: (shop_id?: string) =>
    request<Session>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ shop_id, title: "新对话" }),
    }),
  getSession: (id: string) => request<SessionDetail>(`/api/v1/sessions/${id}`),
  chat: (id: string, message: string, shop_id?: string) =>
    request<AgentResponse>(`/api/v1/sessions/${id}/chat`, {
      method: "POST",
      body: JSON.stringify({ message, shop_id }),
    }),
  cancel: (id: string) =>
    request<{ ok: boolean }>(`/api/v1/sessions/${id}/cancel`, { method: "POST" }),
  memories: async (shop_id?: string) => {
    const q = shop_id ? `?shop_id=${shop_id}` : "";
    const page = await request<{ items: MemoryItem[]; total: number }>(`/api/v1/memories${q}`);
    return page.items;
  },
  deleteMemory: (id: string) =>
    request<{ ok: boolean }>(`/api/v1/memories/${id}`, { method: "DELETE" }),
  starMemory: (id: string) =>
    request<{ id: string; importance: number }>(`/api/v1/memories/${id}/star`, {
      method: "POST",
    }),
  exports: () => request<ExportItem[]>("/api/v1/exports"),
  metrics: () => request<MetricDef[]>("/api/v1/metrics/dictionary"),
  feedback: (body: {
    session_id: string;
    thumbs_up?: boolean;
    thumbs_down?: boolean;
    error_type?: string;
  }) =>
    request<{ ok: boolean }>("/api/v1/feedback", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getFlags: () =>
    request<Record<string, boolean>>("/api/v1/admin/feature-flags"),
  putFlags: (body: Record<string, boolean>) =>
    request<Record<string, boolean>>("/api/v1/admin/feature-flags", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  runPipeline: (shop_id = "shop_a1") =>
    request<unknown>(`/api/v1/pipeline/run?shop_id=${shop_id}`, { method: "POST" }),
  runWorkflow: (name: string, shop_id = "shop_a1") =>
    request<unknown>(`/api/v1/workflows/${name}/run?shop_id=${shop_id}`, { method: "POST" }),
  getOps: () => request<Record<string, unknown>>("/api/v1/admin/ops"),
  listAlerts: (shop_id = "shop_a1", status = "open") =>
    request<{ alerts: AlertItem[]; open: number; total: number }>(
      `/api/v1/alerts?shop_id=${shop_id}&status=${status}`,
    ),
  scanAlerts: (shop_id = "shop_a1") =>
    request<unknown>(`/api/v1/alerts/scan?shop_id=${shop_id}`, { method: "POST" }),
  ackAlert: (id: string) =>
    request<{ ok: boolean }>(`/api/v1/alerts/${id}/ack`, { method: "POST" }),
};

export type StreamHandlers = {
  onStep?: (content: string) => void;
  onToken?: (content: string) => void;
  onResult?: (resp: AgentResponse) => void;
  onDone?: () => void;
  onError?: (err: Error) => void;
};

/** SSE chat stream — falls back to sync chat if stream fails. */
export async function chatStream(
  sessionId: string,
  message: string,
  shopId: string | undefined,
  handlers: StreamHandlers,
  signal?: AbortSignal,
) {
  const headers = await authHeaders();
  const res = await fetch(`/api/v1/sessions/${sessionId}/chat/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, shop_id: shopId }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(await res.text());
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const lines = chunk.split("\n");
      let event = "message";
      let data = "";
      for (const line of lines) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      const payload = JSON.parse(data);
      if (event === "token") handlers.onToken?.(payload.content || "");
      if (event === "step") handlers.onStep?.(payload.content);
      if (event === "result") handlers.onResult?.(payload as AgentResponse);
      if (event === "done") handlers.onDone?.();
      if (event === "error") handlers.onError?.(new Error(payload.content || "stream error"));
    }
  }
}
