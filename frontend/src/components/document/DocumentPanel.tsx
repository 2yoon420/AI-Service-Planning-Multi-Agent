// DocumentPanel.tsx — 탭 컨테이너
import { useState } from "react";
import type { EventItem, ProjectDetail } from "../../api/types";
import { api } from "../../api/client";
import DraftView from "./DraftView";
import SourcesTab from "./SourcesTab";
import StatsTab from "./StatsTab";

type Tab = "draft" | "sources" | "stats";

export default function DocumentPanel({
  detail, events, onClose,
}: { detail: ProjectDetail; events: EventItem[]; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("draft");

  return (
    <aside className="docpanel">
      <div className="docpanel-head">
        <div className="tabs" role="tablist">
          {([["draft","기획서"],["sources","출처"],["stats","통계"]] as const).map(([k, label]) => (
            <button
              key={k}
              role="tab"
              aria-selected={tab === k}
              className={`tab${tab === k ? " is-active" : ""}`}
              onClick={() => setTab(k as Tab)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="docpanel-actions">
          {detail.draft_available && (
            <a className="btn-primary btn-sm" href={api.draftDownloadUrl(detail.project_id)}>
              DOCX 내려받기
            </a>
          )}
          <button className="btn-ghost btn-sm" onClick={onClose} aria-label="문서 패널 닫기">✕</button>
        </div>
      </div>

      <div className="docpanel-body">
        {tab === "draft"   && <DraftView projectId={detail.project_id} status={detail.status} />}
        {tab === "sources" && <SourcesTab events={events} />}
        {tab === "stats"   && <StatsTab projectId={detail.project_id} />}
      </div>
    </aside>
  );
}
