// StatsTab.tsx — 외부 검토보고서 ④ 대응 (기각·애매 fact를 초안 밖에서 보이게)
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";

const VERIFY_ORDER = ["채택", "애매", "기각", "미검증"];
const TIER_ORDER = ["1차", "2차", "3차"];

export default function StatsTab({ projectId }: { projectId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["facts", projectId],
    queryFn: () => api.getFacts(projectId),
    refetchInterval: 10_000,
  });

  if (isLoading || !data) return <p className="doc-empty">불러오는 중…</p>;

  const bar = (label: string, n: number, total: number, cls: string) => (
    <div className="stat-row" key={label}>
      <span className="stat-label">{label}</span>
      <span className="stat-bar">
        <span className={`stat-fill ${cls}`}
              style={{ width: total ? `${(n / total) * 100}%` : "0%" }} />
      </span>
      <span className="stat-num">{n}</span>
    </div>
  );

  return (
    <div className="stats">
      <section className="stat-block">
        <h3 className="doc-h2">▎ 수집한 근거</h3>
        <p className="stat-total">{data.total}건</p>
      </section>

      <section className="stat-block">
        <h3 className="doc-h2">▎ 검증 판정</h3>
        {VERIFY_ORDER.filter((k) => data.by_verification[k])
          .map((k) => bar(k, data.by_verification[k], data.total, `verify-${k}`))}
        {data.needs_source_check > 0 && (
          <p className="stat-warn">
            ⚠ 출처 확인이 필요한 fact {data.needs_source_check}건 —
            초안에서는 요약에 반영하지 않았습니다.
          </p>
        )}
      </section>

      <section className="stat-block">
        <h3 className="doc-h2">▎ 출처 등급</h3>
        {TIER_ORDER.filter((k) => data.by_source_tier[k])
          .map((k) => bar(k, data.by_source_tier[k], data.total, `tier-fill-${k}`))}
        <p className="stat-note">
          ※ 1차는 인터뷰 · 설문 등 직접 수집 자료, 2차는 통계청 · KOTRA 등 공식 통계,
          3차는 뉴스 · 블로그입니다.
        </p>
      </section>
    </div>
  );
}
