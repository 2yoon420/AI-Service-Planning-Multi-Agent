// api/schemas.py와 정확히 대응한다. 여기 없는 필드는 서버가 주지 않는다.

export type ProjectStatus =
  | "running"
  | "awaiting_review"
  | "completed"
  | "failed"
  | "interrupted";

export interface ProjectSummary {
  project_id: string;
  topic: string;
  target_market: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends ProjectSummary {
  current_step: string | null;   // 사람이 읽는 라벨. 표시용으로만 쓴다.
  next_nodes: string[];          // 노드 ID. 단계 판정은 이걸로 한다(8-2절).
  revision_count: number;
  qa_count: number;
  prompt: string | null;
  draft_preview: string | null;
  draft_available: boolean;
  latest_event_seq: number;
  error: string | null;
}

export type EventKind =
  | "text"
  | "search_result"
  | "fetch"
  | "fetch_failed"
  | "fact";

export interface EventItem {
  seq: number;
  ts: string;
  kind: EventKind | string;      // 모르는 kind가 올 수 있다 — 7-1절
  level: string;
  message: string;
  url?: string | null;
  tier?: string | null;          // "1차" | "2차" | "3차"
  title?: string | null;
  step?: string | null;
  count?: number | null;
}

export interface EventsResponse {
  project_id: string;
  events: EventItem[];
  latest_seq: number;
}

export interface ChatMessage {
  role: "user" | "assistant" | string;
  content: string;
}

export interface FactStats {
  project_id: string;
  total: number;
  by_verification: Record<string, number>;   // "채택"|"애매"|"기각"|"미검증"
  by_source_tier: Record<string, number>;    // "1차"|"2차"|"3차"
  needs_source_check: number;
}

// 백엔드 상수와 맞춰둔 값 (agents/router.py)
export const REVISION_CAP = 5;
export const QA_CAP = 20;
