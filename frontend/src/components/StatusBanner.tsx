// StatusBanner.tsx — 실패·중단 안내
import type { ProjectDetail } from "../api/types";

export default function StatusBanner({ detail }: { detail: ProjectDetail }) {
  const interrupted = detail.status === "interrupted";
  return (
    <section className={`banner ${interrupted ? "banner-warn" : "banner-error"}`}>
      <p className="banner-title">
        {interrupted ? "⚠ 실행이 중단되었습니다" : "⚠ 작업에 실패했습니다"}
      </p>
      <p className="banner-body">{detail.error ?? "원인이 기록되지 않았습니다."}</p>
      <p className="banner-hint">
        {interrupted
          ? "아래에 메시지를 보내면 멈춘 지점부터 이어서 진행합니다."
          : "새 기획서를 시작하거나, 서버 로그에서 원인을 확인해 주세요."}
      </p>
    </section>
  );
}
