import type {
  ChatMessage, EventsResponse, FactStats, ProjectDetail, ProjectSummary,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    // FastAPI는 오류를 {detail: "..."}로 준다. 파싱 실패해도 앱이 죽지 않게 한다.
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch { /* 본문이 JSON이 아니면 statusText를 그대로 쓴다 */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ status: string }>("/health"),

  listProjects: () => req<ProjectSummary[]>("/projects"),

  createProject: (topic: string, target_market: string) =>
    req<{ project_id: string; status: string; created_at: string }>("/projects", {
      method: "POST",
      body: JSON.stringify({ topic, target_market }),
    }),

  getProject: (id: string) => req<ProjectDetail>(`/projects/${id}`),

  getEvents: (id: string, since: number) =>
    req<EventsResponse>(`/projects/${id}/events?since=${since}`),

  getMessages: (id: string) =>
    req<{ messages: ChatMessage[] }>(`/projects/${id}/messages`),

  sendMessage: (id: string, message: string) =>
    req<{ project_id: string; status: string }>(`/projects/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  getDraftMarkdown: async (id: string): Promise<string | null> => {
    const res = await fetch(`${BASE}/projects/${id}/draft/markdown`);
    if (res.status === 404) return null;      // 아직 초안 없음 — 오류가 아니다
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.text();
  },

  getFacts: (id: string) => req<FactStats>(`/projects/${id}/facts`),

  deleteProject: (id: string) =>
    req<void>(`/projects/${id}`, { method: "DELETE" }),

  // 다운로드는 브라우저에 맡긴다 — fetch로 받아 Blob을 만들면
  // Content-Disposition의 한글 파일명이 깨질 수 있다.
  draftDownloadUrl: (id: string) => `${BASE}/projects/${id}/draft`,
};
