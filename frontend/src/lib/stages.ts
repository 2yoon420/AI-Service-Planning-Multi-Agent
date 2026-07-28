import type { ProjectStatus } from "../api/types";

export type StageState = "done" | "active" | "todo";

/** 백엔드 12개 노드를 사용자가 이해할 4단계로 묶은 것.
 *  노드 ID로만 판정한다 — current_step 한글 문자열은 쓰지 않는다(0절 규칙 3). */
export const STAGES = [
  { id: "research", label: "시장조사",
    nodes: ["research", "research_revision"] },
  { id: "analysis", label: "PESTEL · 경쟁사 분석",
    nodes: ["pestel", "competitor", "pestel_revision", "competitor_revision", "join"] },
  { id: "writing", label: "기획서 작성",
    nodes: ["writer"] },
  { id: "review", label: "검토",
    nodes: ["await_review", "router", "capability_qa", "finalize"] },
] as const;

export interface ResolvedStage {
  id: string;
  label: string;
  state: StageState;
}

export function resolveStages(
  nextNodes: string[],
  status: ProjectStatus,
): ResolvedStage[] {
  const base = STAGES.map((s) => ({ id: s.id, label: s.label }));

  if (status === "completed") {
    return base.map((s) => ({ ...s, state: "done" as StageState }));
  }

  const activeIdx = STAGES.findIndex((s) =>
    nextNodes.some((n) => (s.nodes as readonly string[]).includes(n)),
  );

  // next_nodes가 비어 있는 경우: 아직 시작 전이거나, 서버가 값을 못 준 상황.
  // 화면이 깨지지 않도록 전부 todo로 둔다(방어적 처리).
  if (activeIdx === -1) {
    return base.map((s) => ({ ...s, state: "todo" as StageState }));
  }

  return base.map((s, i) => ({
    ...s,
    state: (i < activeIdx ? "done" : i === activeIdx ? "active" : "todo") as StageState,
  }));
}

export const STAGE_MARK: Record<StageState, string> = {
  done:   "✓",
  active: "◐",
  todo:   "○",
};
