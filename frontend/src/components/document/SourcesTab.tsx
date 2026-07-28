// SourcesTab.tsx
import type { EventItem } from "../../api/types";
import { aggregateSources } from "../../lib/sources";
import SourceCard from "../SourceCard";

export default function SourcesTab({ events }: { events: EventItem[] }) {
  const sources = aggregateSources(events);

  if (sources.length === 0) {
    return (
      <p className="doc-empty">
        이 화면에 표시할 진행 기록이 없습니다.
        <br />
        <span className="doc-empty-sub">
          진행 기록은 서버 메모리에만 보관되어 서버를 재시작하면 사라집니다.
          이미 완성된 기획서의 출처는 <strong>[기획서] 탭 → 06 출처 부록</strong>에
          영구 보관되어 있습니다.
        </span>
      </p>
    );
  }

  return (
    <div className="src-list">
      <p className="src-count">{sources.length}개 출처를 열람했습니다</p>
      {sources.map((s) => <SourceCard key={s.url} s={s} />)}
    </div>
  );
}
